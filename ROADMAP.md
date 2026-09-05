# Roadmap to redlines 1.0

**Status:** adopted, 30 August 2026. M0 shipped as 0.6.2 (PyPI, docs site live); M1 complete, 4 September 2026 (block model, both 1.0 readers, profiles, semantic pass, sample pair). Milestones M0–M6 exist on GitHub mirroring this file. The ten calls in section 5 are recorded as accepted.
**Relationship to the other documents:** the `PRD` reference in each row is a requirement number (R*) or a decision number (D*). Decisions now live as ADRs in [`docs/adr/`](docs/adr/README.md); PRD section 6 maps every old D-number onto its ADR.

**Relationship to the PRD:** [`docs/PRD.md`](docs/PRD.md) says what each feature is and why it exists. This file says which release it is in. Where the two disagree, this file wins on release assignment; the PRD's Must/Should tags were reconciled against the adopted plan in its revision 10 (30 August 2026).

## How to read this

Sizes are rough, for one experienced developer working with an agent: **S** is a day or two, **M** is up to a week, **L** is one to three weeks. They are for ranking, not estimating. Each feature cites its PRD requirement so you can look up the detail. Section 5 lists the places where I trimmed 1.0 below what the PRD currently says; those are the decisions this file exists to surface.

## 1. Releases at a glance

| Release | What it proves | Contents in one line |
|---|---|---|
| **0.6.x** (hygiene) | The flat engine is trustworthy while 1.0 is built, and there is somewhere to publish | autojunk off, cleanup pass, sentence mode keeps paragraphs, regression corpus, benchmark failure investigation, documentation moved from pdoc to Astro Starlight |
| **1.0** (the slice) | Structural, semantic, format-neutral comparison works end to end on text and markdown | block model + semantic layer + profiles; text and markdown readers; alignment with moves and renumbering; change tree and JSON schema; annotated, summary, markdown, rich and HTML renderers; verify; CLI; compatibility layer; benchmark |
| **redlines-mcp 0.1** (with 1.0) | Agents can compare, verify and author profiles | tools, prompts, resources, skill, golden tests; stdio transport |
| **Site 1.0** (after MCP) | A visitor sees the thesis in one click | A demo route added to the docs site: Pyodide, text and markdown inputs, sample pair by default, block-change list, annotated view, summary, JSON |
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
| Investigate the 18 `neurotic_docx_bench` failures | step 1 | S | Read-only investigation; fix only if trivial. **Resolved, #96:** none of the 18 are redlines failures — all die in the benchmark adapter's python-docx extraction before `Redlines` is ever constructed. Nothing to fix in 0.6.x. Carried forward as #110 (a preview of the 1.1 DOCX reader's failure modes) |
| Documentation site on Astro Starlight in `site/`, replacing pdoc as the publishing surface | ADR-0026, N6 | M | Scaffold, migrate what already exists (quickstart from the README, agent guide, ADR index, contributing), build pdoc into `/api/`, rewrite the Pages workflow. The agent guide moves whole and marked as the 0.6 guide, per ADR-0027; `llms.txt`, the per-page markdown export and a `/schemas/` location are stood up here so M4 writes into slots that exist. Nothing in `site/` may block a release |

**Exit:** 0.6.x on PyPI; existing test suite green; the repetitive-schedule case reports a two-token change; the docs site is live on GitHub Pages with the agent guide, the ADR index and the API reference under `/api/`.

**Shipped, 30 August 2026.** 0.6.2 is on PyPI; the docs site is live at [houfu.github.io/redlines](https://houfu.github.io/redlines/); the "M0 0.6.x hygiene" GitHub milestone is closed, 6 of 6 issues.

**Why this milestone.** The site work is independent of every engine milestone, so it neither blocks nor is blocked — and doing it first means the 1.0 pages that M4 owes (schemas, rewritten agent guide, benchmark report) are written once, onto a site that can hold them, instead of being written for pdoc and then migrated. It also settles the `site/` directory before M6 depends on it.

pdoc is kept here deliberately rather than replaced along with the publishing surface. The reference it produces is a foreign body on the site — its own theme, its own search, HTML only, so it is absent from `llms-full.txt` — but every one of those costs is lowest while the API is still being rebuilt, and the migration is scheduled into M4. Bring it forward if profile authoring in M1 needs API objects embedded in hand-written pages: that is a capability pdoc does not have at all, and it would be a reason to move early rather than on schedule.

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

**Complete, 4 September 2026.** All three exit criteria are met: the section 3a pair is frozen in `tests/corpus/sample_pair/` as four expected trees, read by both readers under both profiles and checked by `tests/test_sample_pair.py`; all seven § 6b hard cases have tests under `tests/corpus/hard_cases/`, four passing and three strict `xfail` with reasons, per the bar set when the milestone was planned; and a blocking `pyodide` job in `python-package.yml` builds the wheel and imports it under Pyodide on every push. All 12 issues on the "M1 Block model, semantic layer, profiles, readers" GitHub milestone are closed. The address syntax ADR-0012 left open is settled in [ADR-0029](docs/adr/0029-address-syntax.md), and the reporting semantics ADR-0006 made mandatory in [ADR-0030](docs/adr/0030-matched-by-and-confidence.md).

The Pyodide check earned its place on its first run, which is the argument for having scheduled it here rather than at M6: it found that the package imports `typing_extensions` without declaring it, so a clean install on Python 3.10 — and every browser build — was already broken. Fixed in the same change.

**Carried forward.** Two decisions this milestone surfaced and deliberately did not take. The profile format's three role match kinds are all structural, so no built-in profile can assign `clause` or `sub_clause`, and 72 of the 102 blocks in the sample pair carry no role at all; whether the format grows a fourth `text` match kind was [#130](https://github.com/houfu/redlines/issues/130), decided at the start of M2 in ADR-0031: two match kinds that look at the block itself, `text` and `label`, with a `kind` filter, and `clause`/`sub_clause` rules in both built-ins. And ADR-0028's revisit condition on composition is now met — the `markdown` profile repeats most of `contract`'s span extractors and role rules — with the evidence pinned in a test and the `extends:` question left open.

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
| Agent guide decomposed into one contract page plus task pages included from `examples/` | N6, ADR-0027 | M | Not a rewrite of one document: the contract goes on a single fetchable page, the tasks become pages whose code CI executes |
| JSON schema and profile schema published as pages, with a worked example each | N6, ADR-0026 | S | MDX, so the examples are real output rather than pasted |
| Benchmark report from M2 published on the docs site | ADR-0021, N6 | S | It is the external quality signal; it needs to be readable, not a file in the repository |
| Performance check: 2,000-block markdown pair under five seconds native | N2 | S | |
| API reference migrated off pdoc onto a `griffe`-based generator | ADR-0026, N6 | S | Deferred to here on purpose. The API roughly triples through M1–M3 and `Redlines` becomes a facade over a new core, so the reference's job changes; and the Starlight-side tooling is weeks old, which only time can settle. Docstring conventions are fixed from M0 so this stays a configuration change. Trial on `claude/trial-starlight-pydocs` |

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
| Demo route in the docs site, Pyodide in a web worker, loads the published wheel | R37, D23, ADR-0026 | M | The site and its deployment already exist from M0; this adds a route and an island |
| Two inputs: drop or upload txt/md, or paste; sample pair loaded by default; friendly "coming in 1.1" for other types | R38 | M | |
| Views: block-change list with roles and addresses, expandable inline redlines; annotated document; summary; JSON with copy; `dropped` notice | R39 | M | Density view moved to 1.1, see section 5 |
| Profile selector with the built-ins and a paste box for a custom profile | R1e | S | |
| Progress state; 2,000-block pair under ten seconds after load | R40 | S | |
| Privacy statement; no upload endpoint; no content analytics | R41 | S | |
| Browser matrix and a clear failure message when Pyodide cannot load | R42 | S | |
| Demo ships from the same Astro project as the docs — no second build, no second deployment | section 13, ADR-0026 | S | PRD section 13's "where the site lives" question, now decided |
| Documentation pages link to the demo, and the demo links back to the guides | ADR-0026 | S | The demo is the fastest explanation the project has; every page should be one click from it |

**Exit:** demo route live on GitHub Pages alongside the docs; sample pair renders on first load; a pasted 100-page markdown contract completes within budget on a mid-range laptop.

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

## 5. Calls that trim 1.0 below the PRD — accepted, 30 August 2026

All ten calls below are **accepted** as written. Nothing here has changed the milestone tables — M1 through M6 were already built on these calls, all 12 M1 issues cite this roadmap as authoritative, and issue [#101](https://github.com/houfu/redlines/issues/101) already treats call 5.1 as settled. Accepting them turns that existing fact into a recorded decision rather than a new one. [`docs/PRD.md`](docs/PRD.md) is annotated to match as of its revision 10.

1. **Accepted. `legislation` profile to 1.1.** The demo scenario is a contract and the primary persona's inputs are contracts and LLM drafts. PLUS Explorer and legislation work stay a 1.1 case; revisit only if a statute needs to be in the demo before then.
2. **Accepted. Profile auto-selection to 1.1.** 1.0 defaults to `contract` for plain text and `markdown` for `.md`, with `--profile` to override. Auto-selection is scoring logic that can wait until there are more than three profiles.
3. **Accepted. Verify text-anchor scope to 1.1.** Addresses, labels and roles cover the agent use case; free-text anchors bring the ambiguity problem adeu is fighting.
4. **Accepted. MCP HTTP transport to 1.1.** Claude Code, Claude Desktop and Cursor all use stdio. HTTP matters for hosted agents, which are not the first audience.
5. **Accepted. MCP `explain_changes` prompt to 1.1.** Useful, but the profile loop is the distinctive thing and the summary tool already gives a model what it needs.
6. **Accepted. Annotated renderer promoted to 1.0 Must.** The PRD hedged; the MCP `summary` and `annotate` tools need it, so it is in M3.
7. **Accepted. HTML renderer kept minimal in 1.0.** Block list plus expandable redlines; the site adds interaction on top rather than a second renderer.
8. **Accepted. Table alignment kept minimal in 1.0.** Row insert/delete and cell inline diff for markdown pipe tables; no column operations, no merged cells. Enough for the sample pair's inserted row.
9. **Accepted. Site density view to 1.1.** The stats exist in the JSON from M2; drawing them is UI work that does not prove anything new.
10. **Accepted. Hand-labelled benchmark set capped at ten pairs for 1.0.** Enough to catch a wrong move; expansion is ongoing work.

Any of these can still be overturned later; if one is, the size lands in the milestone named in the PRD reference and that milestone's exit criteria should be re-read.

## 6. What is deliberately not sized here

The profile format design (M1) and the JSON schema (M2) are design tasks whose cost is thinking rather than typing; they are marked M but could be a week of argument each. The benchmark labelling (M2) is human time. Registry listings and the agent guide are writing. None of these should be squeezed to hit a date; they are the parts a fast implementation cannot make up for.
