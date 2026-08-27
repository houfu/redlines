# PRD: redlines 1.0 — a structural redliner

**Status:** draft for discussion, 27 August 2026 (revision 8: the documentation platform is decided in ADR-0026 — Astro Starlight, in one site with the demo — which adds section 7.12 and resolves the last of section 13's site questions. Revision 7: decisions hived off into ADRs under `docs/adr/`; section 6 is now an index and a D-number map)
**Owner:** houfu
**Companions:** [`docs/adr/`](adr/README.md) (the decisions, with rationale and alternatives — section 6 maps the old D-numbers onto them), [`docs/competitive-landscape-2026-08.md`](competitive-landscape-2026-08.md) (the landscape survey the decisions rest on), and [`ROADMAP.md`](../ROADMAP.md) (the authority on which release each feature is in; where the Must/Should/1.1 tags below disagree with it, the roadmap wins once curated)

---

## 1. Why this document exists

redlines is a 2023 design: flatten a document into one token stream, mark paragraph boundaries with a `¶` token, run one `difflib.SequenceMatcher`, render the opcodes. It has done well on that design (3.7M downloads, the DeepLearning.AI course, an agent-first CLI), and it is now stuck on it. The 2026 field has moved to typed document models and tracked-changes output for AI agents, but every competitor is bound to OOXML and none exposes a change model above "these words changed in paragraph 37".

This PRD defines redlines 1.0 as a **format-neutral structural comparison engine**: documents become trees of blocks, blocks are aligned before text inside them is diffed, and the result is a change tree with human-readable addresses that a person can review and an agent can act on. It records the decisions that shape that product, with alternatives and status, so they can be argued with before code exists.

## 2. Problem

Three groups have a problem the flat spine cannot solve.

Developers building LLM and agent pipelines need to answer "what did the model change, where, and was that all it was supposed to change" in a form they can log, assert on and show to a human. Today they get a global list of token spans and a markdown string. They cannot ask about clause 7.2, cannot tell a move from a delete-plus-insert, and cannot verify scope.

People comparing two versions of a structured document (contracts, policies, legislation, long markdown) think in clauses, sections and rows. A flat diff of a document where a clause moved shows a large deletion and a large insertion, and a renumbering shows every label as changed. Word Compare and the commercial tools handle some of this inside DOCX; nothing does it for markdown, plain text, PDF-extracted text or HTML, which is where most agent-era content lives.

redlines' own users hit silent cliffs in the current engine: `autojunk` marks whole repetitive schedules as replaced, adjacent edits split by punctuation count as two changes, and sentence mode discards paragraph structure. These are symptoms of structure living in a token instead of a model.

## 3. Goals and non-goals

**Goals for 1.0**

G1. Compare two documents of any supported format and return a change tree whose nodes are block-level operations (insert, delete, modify, move, renumber) containing inline operations, each addressable by a stable, human-readable path.

G2. Keep the existing string API, markdown styles, JSON v1 output and CLI working unchanged, implemented over the new core.

G3. Give agent pipelines two first-class operations beyond compare: a deterministic plain-text summary of changes for LLM consumption, and a verification that an edited document changed only what it was permitted to change.

G4. Read plain text and markdown in the core with no third-party dependencies; read DOCX through an optional extra.

G5. Produce tracked-changes DOCX by delegation to an existing applier rather than by writing OOXML.

G6. Publish an alignment benchmark (metric, corpus, baselines) so that the structural claims are measurable and so that the project has an external quality signal beyond the visual-fidelity benchmark it currently sits at the bottom of.

**End deliverables.** Two things must exist at the end of this cycle, and the library work above is in service of them:

G7. **An MCP server** (`redlines-mcp`, a separate package) that gives agents compare, summary, annotate, verify and block-reading tools over local files or inline content, and, distinctively, lets a model *author a structure profile* for a new document family through a prompt-plus-preview loop (D26, D30) without any model call inside the library. It ships with a skill file and registry listings, first, immediately after the 1.0 core, because it reaches the primary persona directly and forces the change-tree, summary, verify and profile contracts to be right.

G8. **A demo website** where a visitor drops two plain-text or markdown files, or pastes text, and gets the structural comparison rendered: block-level changes with roles and addresses, inline redlines within them, the annotated document, the LLM summary, and the JSON to copy. It runs entirely in the browser (Pyodide/WASM), so documents never leave the visitor's machine and hosting is static. It is a usable tool, not a screenshot: it must handle a 100-page contract in markdown. A built-in sample pair (section 3a) shows every capability in one click.

**The 1.0 slice.** 1.0 is deliberately the smallest thing that demonstrates the thesis end to end: text and markdown readers, the semantic pass, block alignment with moves and renumbering, the change tree, the annotated and summary renderers, verify, the CLI, the MCP server, and the site. Every other format is 1.1 or later. The reason is that the top requirements (semantic roles, alignment, moves) need clean text and nothing else; PDF brings layout analysis and OCR questions, DOCX brings a dependency and a reader to maintain, and neither adds anything to what the demo has to prove.

**Non-goals for 1.0**

DOCX, PDF and HTML reading (1.1). A bespoke OOXML parser or writer. Inline formatting change detection (bold, italic, style) as a diff category. Comments, footnotes, headers and footers. Images. **OCR of any kind, and any call to an LLM from inside the library**: the semantic pass is deterministic heuristics over text, always. Real-time or collaborative diffing. A desktop or native GUI. Three-way merge. Server-side processing or storage of uploaded documents on the demo site.

## 3a. The demo scenario

The site, the CLI examples, the MCP `SKILL.md` and the README all use one sample pair, so that a visitor sees every capability without uploading anything. The pair is a short services agreement in markdown, about forty clauses with a definitions section, a schedule and one table, and an amended version that contains, deliberately, one of each thing the engine detects: a definition whose text changed ("Confidential Information"); a clause moved from section 7 to section 9 with a small edit inside it; a renumbering caused by an inserted clause; a cross-reference updated to follow the renumbering; a deleted sub-clause; an inserted table row; a whitespace-only change that should be reported as nothing; and an edit inside a repetitive schedule, which the flat 0.6 engine gets wrong and the structural engine gets right. The expected change tree for this pair is a golden file; it is the first test written and the last one allowed to fail.

## 4. Users

The primary user is the **LLM/agent pipeline developer**: writes Python, uses redlines in a notebook, a Streamlit app, a test suite or an agent loop; wants JSON, deterministic output, and a CLI; increasingly wants an MCP surface. Everything in 1.0 is sequenced for this person, and the MCP server (G7) is their front door.

The secondary user is the **document engineer** with two versions of a structured document who wants clause-level comparison without Word. This person drives the block model and alignment requirements but does not drive DOCX fidelity work in 1.0. The demo site (G8) is their front door, and the one that turns a curious visitor into a library user.

The user who must not be harmed is the **course learner and notebook author** who does `Redlines(a, b).output_markdown` and expects the same string tomorrow.

## 5. Product principles

Format-neutral at the boundary: anything that can be turned into blocks can be compared. Inspectable in the middle: the change tree is data first and rendering second. Addressable: every change has a path a human would recognise. Honest about scope: when a reader drops content (a table, a header), the output says so. Zero-install core: `pip install redlines` keeps working with stdlib, click and rich only.

## 6. Decisions

The decisions behind this PRD, with their alternatives, rationale and revisit conditions, live as architecture decision records in [`docs/adr/`](adr/README.md). They were moved out of this document deliberately: a PRD gets rewritten as the product changes, and rewriting erases reasoning. An ADR is written once and superseded rather than edited, so the trail survives.

Read [`docs/adr/README.md`](adr/README.md) for the index and the conventions. The load-bearing ones, if you read only four: [ADR-0001](adr/0001-format-neutral-structural-engine.md) (why a structural engine at all), [ADR-0005](adr/0005-minimal-core-open-semantic-layer.md) and [ADR-0006](adr/0006-structure-profiles.md) (the semantic layer and declared structure, which are what set this apart), and [ADR-0013](adr/0013-the-1-0-slice-text-and-markdown.md) (why 1.0 is only text and markdown).

### Traceability from earlier revisions

Revisions 1 to 6 of this PRD numbered decisions D1 to D30 in a table here. That numbering is referenced in the requirements below, in `ROADMAP.md` and in earlier conversation, so the mapping is preserved:

| Was | Now |
|---|---|
| D1 | ADR-0001 Format-neutral structural engine |
| D2 | ADR-0002 Primary persona |
| D3 | ADR-0003 Compatibility facade |
| D4 | ADR-0004 Stdlib core, optional extras |
| D5 | ADR-0005 Minimal core, open semantic layer |
| D6 | ADR-0008 Multi-pass block alignment |
| D7 | ADR-0009 Moves before splits |
| D8, D9 | ADR-0010 Keep difflib for leaf diffs |
| D10 | ADR-0011 JSON canonical, annotated renderer |
| D11 | ADR-0012 HTML-like addresses |
| D12, D16, D24 | ADR-0013 The 1.0 slice: text and markdown |
| D13 | ADR-0014 No OOXML writing |
| D14 | ADR-0015 Verify mode in 1.0 |
| D15 | ADR-0016 Summary renderer in core |
| D17 | ADR-0006 Structure profiles (the plain-text reader's rules are profile-driven) |
| D18 | ADR-0017 Separate MCP package |
| D19 | ADR-0021 Alignment benchmark |
| D20 | ADR-0022 Keep the name |
| D21 | ADR-0023 Python support and typing |
| D22 | ADR-0024 No formatting change detection |
| D23, D27, D28 | ADR-0019 Client-side demo site |
| D25 | ADR-0020 MCP before site |
| D26 | ADR-0018 MCP tools, prompts and resources |
| D29 | ADR-0025 CLI as a thin skin |
| D30 | ADR-0006 Structure profiles |
| (non-goal) | ADR-0007 No OCR, no LLM in the library |

Decisions taken after revision 7 have no D-number and appear only as ADRs: [ADR-0026](adr/0026-docs-site-on-astro-starlight.md), the documentation platform.

## 6a. Change-tree wire format

The JSON-versus-XML question and the evidence behind it are recorded in [ADR-0011](adr/0011-json-canonical-annotated-renderer.md). Summary: JSON is canonical, schema-published and versioned; an annotated-document renderer (changes marked in place, CriticMarkup for text and markdown) is the second first-class representation, and is what a model should read when it needs surrounding context.

## 6b. How plain text becomes structure (design note; the decision is ADR-0006)

The plain-text reader runs five mechanical stages, and then the semantic pass runs on the result. Each stage records what it decided and why, so a mis-parse is visible.

**Normalise and segment.** Line endings and whitespace are normalised; the text is split into candidate paragraphs on blank lines; hard-wrapped lines are re-joined when a line ends mid-sentence and the next begins lowercase. This is what 0.6 does today, made explicit.

**Detect labels.** Each candidate paragraph is tested for a leading label from the active profile's patterns (`1.`, `1.1`, `(a)`, `(i)`, `A.`, `Article 5`, `Section 3`, `Schedule 2`, `§ 4`, `4.—(1)`). The label is stripped and kept as `label`; its style (decimal-dotted, alpha-paren, roman-paren, word-prefixed) is kept for the next stage. Unlabelled paragraphs are continuation candidates.

**Infer hierarchy.** Decimal-dotted labels carry their own depth and nest by arithmetic. Alpha and roman labels are ambiguous in isolation ("(i)" after "(h)" is alphabetic; after "7.2" it is roman and one level deeper), so depth is resolved from the label-style stack: a style already on the stack pops back to its level, a new style pushes one deeper. Headings the profile marks as numbering resets (schedules, annexes, parts) open a new section and clear the stack, which is what makes labels unambiguous again after a schedule boundary. Indentation is a secondary signal where it survives.

**Attach continuations.** Unlabelled paragraphs following a labelled block become its body children unless a heading rule claims them.

**Recognise headings.** Short lines in all caps or title case without terminal punctuation, followed by labelled content, score as headings; the score is kept rather than thresholded away, and a profile can tighten or loosen the rule.

**Semantic pass.** On the tree, not the text: a section whose heading matches the profile's definitions rule, or whose children mostly match the *quoted term, "means", text* shape, gets role `definitions` and its children role `definition` with a `defined_term` span; blocks under a schedule heading get role `schedule`; text matching the profile's citation patterns becomes a `cross_reference` span carrying the referenced label, which is what lets the engine later say "cross-reference updated to follow renumbering" rather than "text changed"; parties, dates and amounts are span regexes; emphasis exists only where the format has it (markdown).

**Markdown.** The markdown reader replaces the first three stages with the syntax itself (`#` depth, list markers, pipe tables, fences) and then runs the same label detection on list-item and paragraph text, the same continuation logic, and the same semantic pass under the `markdown` profile. A markdown contract with `## 7. Termination` and `1.` list items therefore gets the same roles and labels as its plain-text twin.

**Profiles (D30).** All of the above is parameterised by a profile: which label patterns exist and their precedence; which headings reset numbering; heading rules; role rules; span extractors. The built-in `contract`, `legislation`, `markdown` and `generic` profiles cover the demo and the primary persona; auto-selection scores a sample of the document against each and reports the winner and confidence. A profile is short enough for a person to write for their own precedent bank in half an hour and for an LLM to draft from a sample document in one prompt, outside the library. The library's contract is: apply the profile deterministically, report `matched_by` and confidence per block, and degrade to one block per paragraph, with alignment still working, when nothing matches.

**Known hard cases,** to be in the test corpus from the start: alpha/roman ambiguity at `(i)`; numbering that restarts inside schedules; one-line clauses that look like headings; definitions written as a run-on paragraph rather than a list; cross-references in prose ("the preceding sub-clause"); documents that mix two label styles because two drafters edited them; and text extracted from PDF with page headers interleaved, which is out of 1.0 but should not crash the reader.

## 7. Functional requirements

Requirements are numbered for traceability and written so each is testable. "Must" is 1.0; "Should" is 1.x; "May" is later.

### 7.1 Block model

R1. A document is an ordered tree of blocks. Each block has a kind from a closed set (`document`, `section`, `heading`, `paragraph`, `list_item`, `table`, `row`, `cell`, `unknown`), text, an optional label, a depth, a path derived from position, and an `attrs` mapping for reader-specific detail. **Must.**

R1a. Each block may carry an optional semantic `role` and a list of semantic `spans` (type, start, end) per D5; the vocabulary is open, with a recommended set documented and used by the built-in heuristics. **Must.**

R1b. A pluggable semantic pass runs after reading and before alignment, assigning roles and spans from the active profile's rules (clause labels, "means" definitions, quoted defined terms, cross-references to labels, party names, dates, amounts). The built-in profiles ship in core; users can register their own passes and profiles. **Must.**

R1d. Structure profiles per D30: a documented declarative format; built-in `generic`, `contract`, `legislation`, `markdown`; explicit selection or auto-selection with reported confidence; per-block `matched_by` and confidence; a tree-level fallback count. **Must.**

R1e. A profile can be loaded from a file or passed as a mapping at call time, from the CLI (`--profile`), from the MCP tools, and by pasting on the site, so a profile drafted by a model in one place is reusable everywhere. **Must.**

R1f. The profile format is flat, plainly named and commented, with a published schema, so that a model given the schema and one built-in example can write a valid profile for a new document family in a single turn; this legibility is a design requirement, not a documentation nicety. **Must.**

R1c. Change nodes carry the role of the block they affect and the span types touched, so summaries can say "definition modified" or "cross-reference inserted". **Must.**

R2. Block text is the comparison key; `attrs`, roles and spans never drive alignment or diffing in 1.0, except that role may break ties between otherwise equal fuzzy candidates. **Must.**

R3. Every reader reports what it dropped (kinds and counts) so output can disclose scope. **Must.**

### 7.2 Readers

R4. Plain-text reader per D17. **Must.**
R5. Markdown reader per D16, stdlib regex only. **Must.**
R6. DOCX reader per D12 as the `[docx]` extra. **1.1.**
R7. A reader interface so users can supply their own (HTML, DOCX, Akoma Ntoso, JSON, anything) by producing blocks; documented with a worked example so a third party can contribute a reader without touching the core. **Must.**
R8. HTML reader on the stdlib parser. **1.1.**
R8a. PDF reader as the `[pdf]` extra on pypdf, text extraction only, structure flagged as inferred; never OCR. **1.1.**
R8b. Format detection from extension and content sniffing for the 1.0 formats (txt, md), extensible for later readers; unknown types are reported, not guessed. **Must.**

### 7.3 Alignment

R9. Multi-pass alignment per D6 with configurable thresholds and a record, per aligned pair, of which pass matched it. **Must.**
R10. Move detection: an unmatched deleted block that matches an unmatched inserted block elsewhere at or above the fuzzy threshold is reported as a move, with both addresses. **Must.**
R11. Renumbering: matched content with differing labels is reported as a renumber, not as inline text edits of the label. **Must.**
R12. Split and merge detection. **Should.**
R13. Alignment is deterministic for identical inputs and configuration. **Must.**
R14. Tables align row by row, then cell by cell; row insert/delete is reported at row level. **Must** for DOCX and markdown pipe tables.

### 7.4 Leaf diff

R15. Word-level diff inside aligned pairs with `autojunk` disabled and the cleanup pass from D8. **Must.**
R16. Sentence-level leaf tokenisation as an option, paragraphs preserved (D9). **Must.**
R17. Leaf diff is pluggable (processor interface retained). **Must.**

### 7.5 Change tree and outputs

R18. A change tree per D10 with block operations `insert`, `delete`, `modify`, `move`, `renumber` and, from 1.1, `split`, `merge`; `modify` nodes contain inline `insert`, `delete`, `replace`. **Must.**
R19. JSON v2 serialisation with a published schema; v1 JSON unchanged and still produced by the existing method. **Must.**
R20. Markdown, rich-terminal and HTML renderers over the tree, byte-identical to 0.6 output for the plain-string path on the existing test suite. **Must.**
R21. LLM summary renderer per D15, built in the MCP milestone, implemented in core. **Must.**
R21a. Annotated-document renderer per section 6a: the source text with changes marked in place (CriticMarkup for text and markdown; tag variant for HTML), block roles shown as prefixes. **Should** in 1.0, **Must** before the MCP server's `summary` tool ships.
R22. Per-block and per-section statistics; change density by section. **Must.**
R23. Filtering: changes by kind, by address prefix, by label, by minimum size. **Must.**

### 7.6 Verify

R24. `verify(original, edited, allowed)` where `allowed` is a set of addresses, labels or text anchors; returns a result with pass/fail, out-of-scope changes, and structural side effects. **Must.**
R25. Verify treats whitespace-only and label-only changes as configurable exemptions. **Must.**

### 7.7 DOCX output by delegation

R26. Export the change tree as an adeu edit batch (`ModifyText` with `target_text`, table row operations) and as a superdoc-redlines edits file keyed by block. **Deferred to 1.1** (D13).
R27. When an applier is installed, a convenience call runs the full compare-and-apply round trip and returns DOCX bytes. **Deferred to 1.1** (D13).
R27a. The change tree's design must not preclude R26: every inline change must be recoverable as (block address, old text, new text) with enough surrounding context to anchor a text search. **Must** in 1.0.

### 7.8 CLI and agent surface

R28. `redlines compare A B` accepts .txt, .md, `-` for stdin and bare strings; defaults to the new tree output when either input is a file, v1 JSON when both are bare strings (compatibility); `--format` overrides. **Must.**
R29. `redlines summary A B`, `redlines annotate A B` and `redlines verify A B --allow ...`. **Must.**
R30. Existing subcommands (`text`, `markdown`, `stats`, `json`) and the command-less default unchanged. **Must.**
R30a. CLI and MCP share one argument-normalisation layer (path, stdin or inline content; format hint; size limit) so behaviour is identical across the two skins (D29). **Must.**

### 7.9 MCP server (`redlines-mcp`, deliverable G7)

R31. Separate package depending on a pinned compatible range of `redlines`; `redlines-mcp` console entry point; stdio and streamable HTTP transports. **Must.**
R32. Tools per D26: `compare` (change tree JSON), `summary` (summary text), `annotate` (annotated document), `verify` (verification result), `read_blocks` (one document's block tree, for picking addresses), `preview_structure` (block tree with `matched_by`, confidence and fallback count under a given profile), `validate_profile` (schema and pattern errors, with line references). Each accepts a path or inline content, an optional format hint, and an optional profile by path or inline. **Must.**
R32a. Prompts per D26: `draft_profile`, `refine_profile`, `explain_changes`; each is a template the server fills from its resources and the user's document sample, so the model receives the profile format, a worked example and the target text in one turn. **Must.**
R32b. Resources: the profile schema, every built-in profile, the change-tree schema, and the skill text, each addressable by URI so a client can read them without a tool call. **Must.**
R32c. The profile-authoring loop (draft → `preview_structure` → refine → `compare`) is documented as the canonical workflow in the skill text, with a worked transcript against the section 3a sample; a golden test replays it with a fixed profile draft. **Must.**
R33. Tool and prompt descriptions and a `SKILL.md` written for models: when to use which tool, how to read addresses and confidence, how to build an `allowed` scope, how to author and save a profile. **Must.**
R34. Size guards: inputs above a configurable limit return an error naming the limit rather than timing out; responses can be truncated by block count with a continuation hint. **Must.**
R35. Listed in the MCP registries agents actually use (the official registry, Smithery, glama), with a one-line install for Claude Code, Claude Desktop and Cursor. **Must.**
R36. Golden tests that call every tool over stdio with fixture documents and compare against stored JSON. **Must.**

### 7.10 Demo site (deliverable G8)

R37. Static site, no backend; loads the published `redlines` wheel into Pyodide in a web worker so the UI stays responsive. No extras needed in 1.0. **Must.**
R38. Two inputs, each either a dropped/uploaded file (txt, md) or pasted text; format detected per R8b; other file types produce a friendly "not yet, coming in 1.1" message; the section 3a sample pair loads with one click and is the default state of the page. **Must.**
R39. Output views: block-change list with addresses and change kinds (insert, delete, modify, move, renumber), each expandable to the inline redline; the summary text; JSON v2 with a copy button; per-file `dropped` notice; per-section change density. **Must.**
R40. Handles a 100-page contract pair in markdown (roughly 2,000 blocks) within ten seconds after the runtime has loaded, with a visible progress state. **Must.**
R41. Nothing leaves the browser: no upload endpoint, no content analytics; a plain statement to that effect on the page. **Must.**
R42. Works without install on current Chrome, Firefox and Safari; shows a clear message when Pyodide fails to load rather than a blank page. **Must.**
R43. Side-by-side pane view with synchronised scrolling. **Should** (1.1).
R44. Shareable permalink that encodes both inputs client-side (compressed in the URL fragment) for small documents. **May.**

### 7.11 Compatibility

R45. The 0.6 public API (`Redlines`, `compare`, `output_markdown`, `output_rich`, `output_json`, `changes`, `get_changes`, `stats`, `opcodes`, processors, `Document`, `PlainTextFile`) keeps working with no code changes; the existing test suite passes unmodified. **Must.**
R46. Deprecation warnings, not removals, for anything superseded. **Must.**

### 7.12 Documentation site (ADR-0026)

R47. Documentation is published from a single Astro Starlight project in `site/`, deployed to GitHub Pages, replacing pdoc as the publishing surface. Hand-written pages and the generated API reference live together, the latter built with pdoc and served under `/api/`; docstrings stay the source of truth for the API reference. **Must.**
R48. By 1.0 the site carries: quickstart and install; the agent guide rewritten for compare, summary, annotate and verify; the JSON v2 schema and the profile schema, each with a worked example; a profile-authoring guide; the alignment benchmark report of ADR-0021; and the ADR index. **Must.**
R49. The demo site of 7.10 is a route in that same project, sharing its build and deployment; documentation pages link to it and it links back. **Must.**
R50. The boundary holds in both directions: nothing under `site/` is imported by the wheel, nothing in the wheel depends on the site building, and a failing site build never blocks a release. **Must.**

## 8. Non-functional requirements

N1. Determinism: identical inputs and configuration produce identical trees, JSON and summaries. N2. Performance: a 200-page contract (roughly 60k words, 2,000 blocks) compares in under five seconds on a laptop in pure stdlib mode and under ten seconds in the browser; the alignment step is at worst quadratic in block count with early exit on exact matches. N3. Memory: block trees hold text once; inline diffs are computed per pair, not over the whole document. N4. Typing: strict mypy, `py.typed`. N5. Packaging: uv-managed, hatchling, extras as in D4; the core wheel and every 1.0 extra import under Pyodide, checked in CI (D28). N6. Documentation: everything in 7.12 — the JSON v2 and profile schemas published with worked examples, an agent guide updated for compare, summary, annotate and verify, and the benchmark report — on the Starlight site of ADR-0026, which is stood up in the 0.6.x hygiene release so that no 1.0 page is written twice; the MCP package and the demo each link back to it. N7. The site and the MCP server are thin: no comparison logic lives outside the core library, so a behaviour seen on the site is reproducible from Python with the same inputs.

## 9. Interface sketch (names, not code)

The new entry point is a single function that takes two inputs of any supported kind and returns a comparison object. The comparison object exposes the source and test block trees, the change tree, statistics, filters, and render methods for markdown, rich, HTML, JSON v2 and summary. A separate `verify` function takes the same inputs plus an allowed scope and returns a verification result. Readers are classes with one method that turns bytes or text into a block tree; the DOCX reader lives behind the extra. The existing `Redlines` class becomes a thin facade that builds a one-block-per-paragraph tree and renders through the same renderers.

I have deliberately not written signatures; that is the first design task once this PRD is agreed.

## 10. Success metrics

For the alignment benchmark (D19): precision and recall of block correspondences, move detection recall, and renumbering recall on the labelled corpus; target ≥ 0.95 correspondence F1 on synthetic mutations and ≥ 0.85 on hand-labelled real pairs at 1.0, with flat redlines 0.6 as the floor and python-redlines as the comparator on DOCX. Per D7, **move detection is a release gate**: 1.0 does not ship with move recall below 0.9 on synthetic mutations or with any move false positive on the hand-labelled set that a reviewer would call wrong. For the semantic layer (D5): precision of role and span assignment on a hand-labelled sample of contracts, reported but not gated in 1.0. For compatibility: the 0.6 test suite passes unmodified, and the course example string is byte-identical. For the MCP server: installable in Claude Code in one command, listed in at least two registries, every tool passing golden tests, and used by at least one external project within a quarter. For the site: loads and runs a 100-page pair within the R40 budget on a mid-range laptop, zero server cost, and visible referral traffic to the PyPI page and repository. For adoption, over two quarters after release: JSON v2 and summary usage visible in issues and dependents; at least one applier integration used in the wild; the benchmark cited by another project.

## 11. Sequencing

Each step ships on its own and is useful without the next.

1. **0.6.x hygiene release.** `autojunk` off, cleanup pass, sentence mode preserves paragraphs, regression corpus with a repetitive schedule, investigate the 18 benchmark failures. Small, immediate, no design risk. The documentation moves from pdoc to Starlight here (ADR-0026, 7.12): it touches no engine code, so it neither blocks nor is blocked, and every page step 5 owes then gets written once, onto a site that can hold it.
2. **Model, semantics and readers.** Block model with the semantic layer (D5), reader interface with a worked third-party example, `dropped` reporting; plain-text and minimal markdown readers; the legal semantic pass; format detection; the section 3a sample pair and its golden tree. Pyodide import check added to CI here. Existing API untouched.
3. **Alignment and change tree.** D6 passes, moves, renumbering, tables; change tree; serialisation per the D10 decision; filters and per-section stats. The synthetic-mutation corpus and metric are built in this step, before alignment is tuned; the move-recall gate (section 10) is measured here.
4. **Renderers and compatibility.** Markdown, rich, HTML and annotated-document renderers over the tree; `Redlines` facade; 0.6 suite green.
5. **Verify, CLI, docs — the 1.0 release.** Verify mode, the three CLI subcommands over the shared argument layer (D29, about a day), agent guide, schema publication.
6. **`redlines-mcp` 0.1 (G7).** Started as soon as the tree serialisation is frozen in step 3, released within days of 1.0: tools, transports, the LLM summary renderer (D15), SKILL.md, golden tests, registry listings.
7. **Demo site (G8).** Started once step 4's renderers are stable; released after the MCP server. A route in the documentation site from step 1 (ADR-0026), so this step is the demo itself and not a second build: Pyodide worker, text and markdown inputs, the output views, the sample pair as the default state, privacy statement.
8. **1.1.** HTML reader, then DOCX reader (D12), then PDF text reader; adeu and superdoc-redlines export (D13); split/merge; side-by-side view on the site; `[fuzzy]` tuning from benchmark results; markdown-it reader only if the regex one proves insufficient.

## 12. Risks

Alignment quality on real documents is the thesis risk: fuzzy thresholds that work on contracts may misfire on prose or on tables of near-identical rows. Mitigation: the corpus and metric are built before tuning, thresholds are configurable and reported, and every match records its pass.

Compatibility drift: re-implementing `output_markdown` over a tree could change whitespace or paragraph handling in edge cases the test suite does not cover. Mitigation: golden-file tests generated from 0.6 across the README, course and issue examples before the facade is written.

Regex markdown and clause-label heuristics will have false positives. Mitigation: heuristics opt-in where risky, `dropped` and `matched_by` reporting so users can see what happened, and an easy path to supply their own reader.

Delegated DOCX output depends on adeu's `target_text` addressing, which is ambiguous on repeated text (their issues #28/#29). Mitigation: emit `match_mode: strict` with enough context, fall back to block-level replacement, and report ambiguities rather than guessing.

Scope creep toward OOXML. Mitigation: D12, D13 and D22 are explicit non-goals with rationale; revisit only with user demand in hand.

Pyodide constraints bite late. A dependency that works on CPython may be missing from the Pyodide index or too slow under WASM. The 1.0 reader set is confirmed to fit (D28), but rapidfuzz is browser-unavailable, so alignment quality on the site is the difflib-ratio floor, not the tuned `[fuzzy]` result; if the two diverge noticeably, the site will under-sell the engine. Mitigation: the CI import check lands in step 2, extras degrade gracefully by design, and the site budget (R40) is measured on a real contract pair before the site is announced.

The 1.0 slice looks thin to a visitor with a Word file. The site turning away a .docx is a real first impression cost. Mitigation: the sample pair is the default state so the capability is visible before any upload; the "coming in 1.1" message is specific; and the DOCX reader is first in the 1.1 queue after HTML.

Semantic heuristics drift toward wanting an LLM. Once roles exist, the temptation is to improve them with a model call. Mitigation: the non-goal is explicit; the semantic pass is pluggable, so anyone who wants an LLM-backed pass can write one outside the library; and the benchmark measures the heuristic pass so its limits are known rather than felt.

Two packages drift. `redlines-mcp` can lag or break against a new core release. Mitigation: compatible-range pinning, the MCP golden tests run against the core's main branch in the core's CI, and releases of the two are cut together.

The demo becomes the product. A site that works well invites feature requests (accounts, history, DOCX download) that pull toward a hosted service. Mitigation: the non-goals in section 3 are explicit; the site's job is to sell the library and the MCP server, and anything that needs a server is out of scope by construction.

## 13. Open questions for you

D10 and D14 are now decided per the recommendations. Next design questions, in order: the profile format (D30) and the built-in set; the path syntax for D11; the JSON Schema for the change tree.

Whether to keep the name (D20; I recommend keeping it; the site's domain is a separate, cheaper decision). Whether verify should also accept a natural-language instruction and ask an LLM to derive the allowed scope, or stay purely deterministic in 1.0 (I recommend deterministic; the LLM layer belongs in the caller, and on the site there is no LLM at all). Whether the site's side-by-side view is 1.0 or 1.1 (I recommend 1.1; the block-change list with expandable redlines is the view that shows what is different about this engine, and side-by-side is what every competitor already has). Whether the MCP server should expose the 0.6 flat comparison as a separate tool for callers who just want the old markdown string (I recommend no; `compare` on two bare strings already returns a one-block-per-paragraph tree, and one fewer tool is easier for models). Whether to approach the adeu and Docxodus maintainers before or after 1.0 (I recommend before, once the JSON v2 schema is drafted, because the schema is the integration point).

**Resolved since revision 7.** Where the site lives: a `site/` directory in the main repository, one Astro project holding the documentation and the demo route together, per ADR-0026 and 7.12.
