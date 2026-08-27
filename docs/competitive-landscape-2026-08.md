# Redlines in 2026: competitive landscape and the case for a structural redliner

*Research note, 26 August 2026. Sources are listed at the end; figures are as reported by PyPI, npm, pepy.tech and GitHub on the day of writing and will drift.*

## 1. Summary

The redlining space has split into two camps since redlines was written in 2023. One camp is **comparers**: give me two DOCX files and I return a DOCX with native Word tracked changes (python-redlines / Docxodus, SuperDoc's Document Engine, Draftable, Litera). The other, newer camp is **edit appliers**: an LLM decides on edits in a text form and the tool projects those edits into a DOCX as `w:ins`/`w:del` (adeu, superdoc-redlines, docx-mcp, Anthropic's docx skill). Every project in both camps is bound to OOXML. All of them treat the diff algorithm as a commodity (diff-match-patch or Myers over words), and none of them exposes a change model that a human or an agent can reason about above the level of "these characters changed in paragraph 37".

redlines is the odd one out. It is format-neutral (strings in, markdown / rich / JSON out), pure Python with no binaries, has an inspectable change model, and has by far the widest distribution of the group (roughly 3.7 million PyPI downloads, ~290k in the last thirty days, against ~98k lifetime for python-redlines and ~91k for adeu). What it lacks is structure: the "spine" flattens a document into one token stream, marks paragraph boundaries with a `¶` token, and runs a single `difflib.SequenceMatcher` over the whole thing. That design has real cliffs (section 4) and cannot express the things lawyers and agents actually ask about, such as "clause 7.2 was moved under section 9 and its notice period changed".

The opportunity is a **structural redliner**: a format-neutral, hierarchical comparison engine that aligns blocks (clauses, headings, list items, table rows) before diffing text inside them, and emits a change *tree* rather than a change *list*. No open-source project occupies that slot. The closest are Docxodus's new `docxdiff` engine (DOCX-only, .NET-bound, structure exposed to Python only through an alpha subprocess client) and the 2026 cohort of Rust and TypeScript "typed-IR" DOCX compilers surfaced by `neurotic_docx_bench` (stemma, safe-docx, folio, jubarte), all of which are OOXML-first and agent-facing. That benchmark has already measured redlines 0.6.1 as a DOCX redliner via a third-party adapter: 45.9 mean on a visual-fidelity metric, 18 failures in 763 documents, bottom of the table, which is what a text-only differ should score on a pixel benchmark and is not the axis to compete on. The February 2026 roadmap in `.planning/` points at DOCX parsing first; this note argues the comparison model, not the parser, is the differentiating investment, and that DOCX reading and writing should be borrowed from the appliers rather than rebuilt.

## 2. The current redlines spine, as it stands

> **A note on `.planning/`.** This survey was written against a working checkout that carried a `.planning/` directory (`PROJECT.md`, `ROADMAP.md`, `REQUIREMENTS.md`, and research notes) from February 2026. Those files are not in this repository and never were. Where the sections below cite `.planning/` or `PROJECT.md`, they are citing that earlier planning material, which the ADRs in [`adr/`](adr/README.md) now supersede.

The library is roughly 2,150 lines across six files on `main` (`pyproject.toml` says 0.6.0; PyPI's latest is 0.6.1, released 24 November 2025 from the `0.6.1` branch). The pipeline is:

1. `split_paragraphs` breaks the text on newlines and rejoins it with a literal `" ¶ "` between paragraphs (`concatenate_paragraphs_and_add_chr_182`). `NupunktProcessor` does the same at sentence boundaries instead, which means paragraph structure is discarded in sentence mode and every sentence becomes its own paragraph on output.
2. `tokenize_text` splits into word-ish tokens with a regex (`(?:[^()\s]+|[().?!-])\s*`), keeping trailing whitespace on each token.
3. Tokens are whitespace-stripped for comparison and fed to `difflib.SequenceMatcher(None, a, b)` with default `autojunk=True`.
4. Every opcode becomes a `DiffOperation` carrying the *whole* token lists of both documents plus one 5-tuple. `Chunk.chunk_location` exists but is always `None`.
5. `Redlines.changes`, `output_markdown`, `output_rich` and `output_json` each walk the opcodes and each independently reconstitute paragraphs by regex-replacing `"¶ "` with `"\n\n"`.

What is good about this and worth keeping: the `Document` and `RedlinesProcessor` abstractions, the `Redline`/`Stats` dataclasses, the JSON schema with both character and token positions, the agent-first CLI, and the multi-target markdown styles. These are the things none of the competitors have.

What is stuck: structure is encoded as a magic token rather than as a model; there is one global alignment with no hierarchy; positions are global token indexes that mean nothing to a reader; renderers all know about `¶`; there is no move, split, merge or renumbering detection; and the `.planning` research from February recommends python-docx while `PROJECT.md` decides on a hand-written OOXML parser, a decision that has not been revisited since the appliers appeared.

## 3. The competitors

### 3.1 superdoc-redlines (yuch85)

Despite the name this is not a SuperDoc project and not a comparer. It is a Node CLI (Apache-2.0, not on npm, install by cloning; ~39 stars) by a Singapore legal-tech developer that runs SuperDoc's ProseMirror editor headlessly under jsdom in "suggesting" mode. The workflow is `extract` (DOCX to a block-ID JSON intermediate representation, `b001`, `b002`, ...), have an LLM produce an edits file (`replace`, `delete`, `insert`, `comment`, `highlight` and range variants keyed by block ID or `findText`), `validate`, then `apply` to get a DOCX with native revisions and comments. The only diffing is inside a `replace`: old block text versus LLM-supplied new text, word-level via diff-match-patch with the lines-to-chars trick applied to words, then `diff_cleanupSemantic`. No moves, no table diff, no formatting changes, TOC blocks cannot be edited, and the output DOCX bloats about 6x until `recompress`. It ships a `SKILL.md` and is listed as a Claude Code skill; the positioning is squarely "agent in Cursor or Claude Code marks up a 100-page contract".

SuperDoc itself (Harbour; AGPL-3.0 plus commercial) added a first-party two-file diff to its Document Engine on 22 March 2026: `diff.capture` / `diff.compare` / `diff.apply({changeMode: 'tracked'})`, available in the JS SDK, a Python SDK (`superdoc-sdk` 2.6.0, released today) and an MCP server. The diff payload is documented as "opaque, intended for replay, not semantic inspection", granularity is undocumented, and header/footer changes are not reviewable revisions in v1.

### 3.2 python-redlines (JSv4 / Open Source Legal)

MIT, ~110 stars, latest 0.3.0 on 10 July 2026, actively maintained. The Python package is a thin wrapper that extracts a self-contained .NET 10 executable from a platform wheel to the user cache and calls it via subprocess with temp files. Two engines: the legacy Open-XML-PowerTools `WmlComparer` (Eric White's 2016 code, archived by Microsoft in 2019, now feature-frozen) and Docxodus, JSv4's .NET fork. Docxodus adds move detection (post-hoc word-level Jaccard similarity, threshold 0.8, minimum three words), run-level format-change detection (`w:rPrChange`), LCS-based row matching for large tables, and, new in 0.3.0 and opt-in, a `docxdiff` engine that works on a typed intermediate representation: Myers token diff within paired blocks, row/cell-precise table diffs, footnote and endnote scope, paragraph split/merge detection, header/footer comparison, paragraph and section property changes, and a round-trip guarantee that `accept(compare(L, R)) == R`.

The API is `engine.run_redline("Reviewer", original_bytes, modified_bytes)` returning `(redline_bytes, stdout, stderr)`; stdout is a one-line revision count. There is **no structured change list, JSON, HTML or text output from Python**. Docxodus has `GetRevisions()`, `GetEditScriptJson()` and `GetSemanticChanges()` in .NET, reachable from Python only through the alpha `docx-scalpel` package (0.1.0a5, linux-x64 wheel only, aimed at agent editing sessions). Documented gotchas: `detect_moves=True` with the WmlComparer engine can produce a DOCX Word refuses to open unless `simplify_move_markup=True` is also set; markup colours are not customisable (issue closed "not planned"); the original engine "often leads to hard crashes on documents with minor format issues".

### 3.3 adeu (Dealfluence Oy)

MIT, Python and TypeScript implementations, ~125–150 stars, extremely active: 90 PyPI releases since August 2025, 3.0.1 released 25 August 2026, Python 3.12+. Tagline "Track Changes for the LLM era"; the framing is "LLMs speak Markdown; reviewers speak Track Changes" and "a Virtual DOM for Microsoft Word". It projects a DOCX to Markdown (headings, lists, tables with cells joined by `|`, bold/italic, footnotes as `[^fn-ID]`, existing revisions surfaced as CriticMarkup with `Chg:N` ids), the LLM edits the projection, and adeu projects edits back as `w:ins`/`w:del` plus comments. Edits are addressed by `target_text` search with `strict`/`first`/`all` match modes and optional regex, not by offsets; a `DocumentMapper` keeps `TextSpan`s that map projected characters back to runs across document parts; validation gates reject cross-part spans, read-only markers and locked content controls before any write. Edit types are `ModifyText`, `AcceptChange`, `RejectChange`, `ReplyComment`, `InsertTableRow`, `DeleteTableRow`, `SetField`.

It does have an `adeu diff a.docx b.docx` command, but it is a word-level diff-match-patch with semantic cleanup, whole-block replacement when word-ratio similarity drops below 0.35, a paragraph alignment path and table-row opcodes; no move detection, no format-change output, images reported as warnings. Distribution is where adeu is strongest: Claude Code plugin, Agent Skill, Claude Desktop `.mcpb`, Gemini CLI extension, Smithery, n8n node, `langchain-adeu`, and a public "docx-benchmark" of agentic editing tasks. Open issues ask for coordinate-based targeting (#28, #29): text-search addressing is a known ceiling.

### 3.4 The rest of the field, briefly

Google's diff-match-patch was archived on 5 August 2024; the PyPI package tracks a community fork and still does ~4.9M downloads a month, and there is a WASM-ready Rust port. jsdiff (Myers, `diffWords`/`diffSentences`) is the JS analogue of redlines' tokeniser. xmldiff 3.0 (June 2026) does tree diff with moves for XML. difftastic does structural diff for code via tree-sitter but explicitly falls back to line diff for prose. Markdown-AST diffing is thin (two small experimental repos). On the editor side, `prosemirror-changeset`, `prosemirror-suggestion-mode` and Tiptap's paid Tracked Changes add-on track *edits as they happen*, which is a different problem from comparing two finished versions.

Commercially, Litera Compare and Word's own Compare remain the reference output; Draftable exposes a JSON change-details endpoint and, in February–March 2026, added an "AI-Ready Redline Export": a deterministic plain-text summary of insertions, deletions and moves designed to be pasted into ChatGPT, Claude, Harvey or Legora. That is an incumbent shipping redlines' output format as a feature. The AI-native entrants (Harvey, Spellbook, Ivo, DraftPilot, Legora, Definely, Microsoft's Legal Agent in Word from April 2026, Claude for Word from April 2026, Copilot in Word's native tracked changes from April 2026) all *deliver* edits as tracked changes; none of them ships clause-level *comparison* across reordered documents. The academic and legislative work (Zhang–Shasha, Chawathe, GumTree; the US House Comparative Prints Suite; UK Lawmaker's Document Compare over Akoma Ntoso) shows hierarchical document diff is well understood in principle and barely productised outside legislatures.

### 3.5 The 2026 cohort and `neurotic_docx_bench`

The benchmark you pointed me to (github.com/jandira-tech/neurotic_docx_bench, AGPL-3.0, ~325 commits, 10 stars) is the most useful single artefact in this survey, for two reasons: it names a further cohort of DOCX comparers that a search for "redlines" does not surface, and it has already measured redlines itself.

The benchmark takes `base.docx`/`next.docx` pairs (763 in the current corpus, with tables, numbering, moves and footnotes), asks each tool to produce a tracked-changes DOCX, renders candidate and Word's own Compare output to PDF through LibreOffice, and scores *pixel* similarity (SSIM, ink-F1, edge-IoU, colour ΔE) at 144 DPI. It is therefore a measure of visual fidelity to Word's markup, not of alignment correctness; a tool that finds exactly the right changes but drops formatting scores badly. Its author, Jandira Technologies (arthur.law, New York and São Paulo), also makes the closed-source Rust/WASM engine "jubarte" that tops the table, so treat the ranking as a vendor benchmark, albeit an unusually transparent one (the scoring core is lifted verbatim from SuperDoc's visual benchmarks and parity-tested).

Current-corpus results on the `script_redlines` suite, mean / median / failures out of 763: jubarte-rust 84.5 / 92.7 / 0; docxodus 9.8.0 80.6 / 91.2 / 4; stemma 0.5.0 62.9 / 61.8 / 149; safe-docx 0.19.1 53.7 / 51.3 / 75; **redlines 0.6.1 45.9 / 47.1 / 18**. SuperDoc 2.0.0, superdoc-redlines 0.2.0, folio and docx-redline-js appear in other suites or legacy runs.

The redlines adapter (`redlines_gen.py`) is instructive about how a third party sees the library. It extracts paragraph text with python-docx (tables, headers and footers deliberately omitted), forces `NupunktProcessor` ("required, better for legal abbreviations / citations"), reads `output_json()["changes"]`, and rebuilds a new DOCX from scratch, writing `w:ins`/`w:del` per change with author and date. The author calls it a "text-level baseline" to measure "how far pure text redlining reaches toward Word's document-level tracked changes". Three things follow. The JSON change model is what got used, which supports section 5. The sentence-mode paragraph reflow described in section 4 almost certainly costs points here, since every sentence lands in its own paragraph before rendering. And the 18 failures are worth pulling from the run logs, because they are the only external failure data redlines has.

The new comparers themselves, briefly. **stemma** (stemma-sh, Rust, Apache-2.0/MIT, 0.x, 0 stars, "built largely by AI under human direction") is a "typed-IR DOCX compiler with first-class tracked-change semantics": `stemma compare base.docx target.docx --author ... -o redline.docx`, block-level typed transformations for insertions, deletions, moves and formatting, JSON via `extract`, an MCP server, and a claim of 95% task success against 76–85% for Claude's stock DOCX skill. **safe-docx** (UseJunior, TypeScript with some Lean, Apache-2.0, 0.15–0.19, ~32 stars) is a surgical-editing toolkit for agents with a `compare_documents` tool producing DOCX and ODF tracked changes, `extract_revisions` returning structured JSON, and MCP tools for read, grep, replace, insert and comment. **folio** (`@stll/folio-core`, TypeScript) and **docx-redline-js** are further TS generators. **jubarte** is closed (five free comparisons at redlines.free, then contact pricing), claims moves and formatting changes, and is the only one with a desktop app.

The pattern across the cohort is uniform: Rust or TypeScript, a typed intermediate representation of OOXML, tracked-changes DOCX as the primary output, an MCP server, and "agents" as the audience. None is format-neutral and none exposes a change model above paragraph granularity.

### 3.6 Comparison matrix

| | **redlines** (0.6.1) | **python-redlines** (0.3.0) | **adeu** (3.0.1) | **superdoc-redlines** (0.2.0) | **SuperDoc Document Engine** |
|---|---|---|---|---|---|
| Kind | Comparer + renderer | Comparer | Edit applier (+ thin diff) | Edit applier | Comparer + applier |
| Language / runtime | Pure Python, stdlib only | Python wrapper over bundled .NET 10 exe | Python 3.12+ and TS/Node 22 | Node 18 + jsdom + SuperDoc | JS SDK, Python SDK, MCP |
| Licence | MIT | MIT | MIT | Apache-2.0 (dep is AGPL) | AGPL-3.0 / commercial |
| Inputs | str, plain text file, any `Document` | DOCX | DOCX (and live Word on Windows) | DOCX + edits JSON | DOCX |
| Outputs | Markdown (6 styles), HTML, rich, JSON | DOCX with `w:ins`/`w:del`/moves/`rPrChange` | DOCX tracked changes + comments; markdown / CriticMarkup; JSON | DOCX tracked changes + comments | DOCX tracked changes; opaque diff payload |
| Diff algorithm | difflib SequenceMatcher over words | WmlComparer LCS over atoms; docxdiff Myers within paired blocks | diff-match-patch words + semantic cleanup | diff-match-patch words + semantic cleanup | undocumented |
| Block alignment | None (¶ token in stream) | Hash + LCS on paragraphs/tables; docxdiff adds split/merge | Paragraph alignment; <0.35 ratio → block replace | Block IDs supplied by caller | undocumented |
| Moves | No | Yes (Docxodus) | No | No | undocumented |
| Formatting changes | No | Yes (run, para, section props) | No | No | styles/numbering applied, not reviewable |
| Tables | No | Row/cell level (docxdiff) | Row insert/delete | No | body only |
| Structured change model exposed | Yes: `Redline`, JSON with positions and stats | No (count only; JSON in .NET/alpha client) | Edit batch JSON; diff hunks | Edits IR JSON | "not for semantic inspection" |
| Granularity control | Paragraph or sentence (nupunkt) processors | `detail_threshold` | None | None | None |
| Agent surface | CLI defaults to JSON; `AGENT_GUIDE.md` | GitHub Action; demo site | MCP, plugin, skill, LangChain, n8n | SKILL.md for Claude Code | MCP server, CLI |
| Adoption | ~158 stars, ~3.7M downloads, ~290k/30d | ~110 stars, ~98k downloads, ~65k/30d | ~125–150 stars, ~91k downloads, ~20k/30d | ~39 stars, not published | n/a |
| Activity | Last release Nov 2025 | Jul 2026 | Aug 2026 (weekly) | early 2026, unknown | Aug 2026 |

## 4. Weaknesses in the current spine, verified

The general point that the spine is flat is qualitative; three specific consequences are reproducible.

**The autojunk cliff.** `SequenceMatcher` is constructed with the default `autojunk=True`. For any sequence of 200 or more tokens, difflib treats every token that occurs more than 1% of the time as "popular" and refuses to start a match on it. In ordinary varied prose this is harmless: on a synthetic 565-token contract with three scattered edits, `autojunk` on and off give identical, correct results (4 operations, 11 tokens changed). On repetitive text it is catastrophic: a 1,050-token block made of one clause repeated thirty times, with a single two-word change, is reported as `('replace', 11, 1050, 11, 1050)`, that is, the entire document replaced, with `autojunk=False` giving the correct two-token replace. Real documents with this shape exist (schedules, price lists, "Intentionally omitted" runs, repeated table rows), and the failure is silent. This is a one-argument fix at the cost of speed, or it disappears entirely once diffs run within aligned blocks, because aligned blocks are short.

**No semantic cleanup.** "thirty (30) days" to "sixty (60) days" becomes two separate `replace` operations split by an equal `(` token. Word, diff-match-patch's `cleanupSemantic`, and every competitor here would render one change. Users of the JSON see two changes and the stats count two.

**Sentence mode loses paragraphs.** Because paragraph and sentence boundaries share the same `¶` marker and every renderer turns `¶` into `\n\n`, `NupunktProcessor` reflows the whole document one sentence per paragraph. This is not a bug in nupunkt; it is the cost of representing structure as a token.

None of these is hard to patch. They matter because they show what happens when structure is encoded as a character in a flat stream rather than modelled.

## 5. What is unique about redlines, and what is not

Not unique, and not worth defending: the word-level diff itself. Every competitor has one and the algorithm is a commodity (difflib, Myers, diff-match-patch are all fine for the leaf level). Rendering strike-through and colour in markdown is also easy to copy; Draftable has effectively done so.

Unique, and worth building on:

*Format neutrality.* redlines is the only library in this group whose input is not OOXML. It can diff LLM output against a prompt, a markdown file against its previous commit, text extracted from a PDF, legislation, a Streamlit textbox. Every DOCX-bound tool has to be handed a DOCX; a great deal of the "new world" content (agent scratchpads, markdown drafts, chat transcripts, HTML) never becomes one. This is exactly why the DeepLearning.AI course adopted it and why the download numbers are an order of magnitude above the others.

*Output neutrality with an inspectable change model.* redlines already returns changes as data with positions and statistics. python-redlines gives a count; SuperDoc says its diff is not for inspection; adeu and superdoc-redlines are appliers, so they never *produce* a comparison of two independently edited versions. The demand for a machine-readable diff is now validated by an incumbent: Draftable's AI-Ready export is a plain-text change summary for LLM consumption. redlines is a pure-Python, open, embeddable version of that.

*Zero-install and small.* No .NET binary extraction, no jsdom, no Node 22, no AGPL dependency. `pip install redlines` works in a notebook, a Lambda, a CI job and a WASM Python runtime.

*The processor abstraction.* Granularity is already pluggable (paragraph, sentence). No competitor exposes that. It is the seed of the structural idea: the question "what is the unit of comparison?" is already a first-class parameter in redlines.

Put together: redlines is positioned to be the **comparison engine in the middle** of the new stack, rather than a competitor at either end. Readers (adeu's projection, python-docx, markdown parsers, Akoma Ntoso) feed it; writers (adeu, superdoc-redlines, docx-mcp, or eventually its own OOXML revision writer) consume its change model. The change model is the product.

## 6. The structural redliner thesis

The design shift is from "diff of a token stream" to "diff of a document tree". Concretely:

**A format-neutral block model.** A document becomes an ordered tree of blocks: section, heading, paragraph, list item, table, row, cell, footnote, with each block carrying its text, its kind, its label or number if it has one ("7.2", "(a)", "Schedule 3"), its depth, a stable path, and optional inline attributes. Plain text is parsed into paragraphs plus recognised numbering patterns; markdown into headings, lists and tables; DOCX into paragraphs, styles, `numPr` and tables. The model is deliberately much smaller than OOXML and much richer than a string.

**Block alignment before text diff.** Source and test block sequences are aligned in passes: exact-content matches first, then label matches ("7.2" to "7.2"), then fuzzy matches by similarity ratio with a threshold, then positional fill-in. Unmatched blocks are inserts or deletes; a deleted block that fuzzy-matches an inserted one elsewhere is a move; a block whose content matches the concatenation of two neighbours is a split or merge; a label change with matching content is a renumbering. This is where Docxodus's `docxdiff` (splits and merges) and its WmlComparer fork (Jaccard moves) are the state of the art to match or beat, and it is where the legislative tools and GumTree-style hierarchical matching are the literature.

**Leaf diffs inside aligned pairs.** Within each aligned block pair, run the existing word or sentence processor. This is the current spine, demoted from "the engine" to "the leaf engine". Aligned blocks are short, so autojunk stops mattering, and semantic cleanup can be applied per pair.

**A change tree, not a change list.** The result is block-level operations (inserted clause 8.4, deleted paragraph under 3.1, moved 7.2 to 9.1, renumbered 5 to 6, split of 12.3, table row added, heading text changed) each containing its inline operations. Every change has an address a human recognises ("7.2, second sentence") and an agent can act on ("block path `/body/section[7]/clause[2]`"). Statistics roll up by section, which gives change density and hotspot detection for free, and covers the deferred `LDOC-01`/`LDOC-02` requirements.

**Renderers over the tree.** Existing markdown, rich and JSON renderers adapt to walk the tree, and the `¶` regex disappears from all of them. New renderers fall out naturally: an LLM-oriented change summary (the open equivalent of Draftable's AI-Ready export), a side-by-side HTML view, and a DOCX writer, either native or by delegating to an applier, which converts the change tree into an adeu or superdoc-redlines edit batch.

**A verification mode.** The Anthropic docx skill uses a diff as a *validator*: strip one author's revisions and text-compare to prove the tracked changes faithfully represent the edit. A structural redliner can answer richer questions of the same kind: did the agent change only clause 12.3 as instructed, did anything move, did numbering survive, what is the change density outside the clauses it was told to touch. That is a product surface no competitor has and every agent pipeline needs.

## 7. Where this competes and where it does not

The closest thing to this thesis is Docxodus `docxdiff`. It has a modeled IR, split/merge detection and a round-trip guarantee, and JSv4 is clearly heading toward agent use with `docx-scalpel`. But it is DOCX-only, lives in .NET, and its structured output reaches Python only through an alpha subprocess client for one platform. A pure-Python, format-neutral structural diff does not have to beat it on DOCX fidelity; it has to be the thing you reach for when the inputs are not two clean DOCX files, and the thing whose output you can read.

adeu and superdoc-redlines are complements, not competitors. adeu's DOCX-to-Markdown projection with `TextSpan` mapping is precisely the reader a structural redliner needs, and its `ModifyText` batch is a writer target. If adeu's authors are receptive, "redlines computes the structural diff, adeu writes the tracked changes" is a coherent joint story; if not, the same integration works at arm's length via its CLI and JSON.

The commercial tools are not reachable from a Python library and do not need to be. The relevant fact is that they have validated demand for LLM-readable change summaries and for clause-level thinking.

## 8. Implications for the February 2026 roadmap

The `.planning` roadmap orders the work as rich tokens, then a custom OOXML parser modelled on SuperDoc's super-converter, then DOCX comparison, then a diff-match-patch study. Given the survey, three of those bets look wrong-sized.

The custom OOXML parser is the largest item and the least differentiating. Since February, adeu has shipped a mature DOCX-to-Markdown projection under MIT, SuperDoc has shipped a Python SDK, and python-docx remains adequate for reading paragraphs, styles, numbering and tables. Writing a parser from scratch competes with three funded teams on the axis where redlines has no advantage.

Rich tokens carrying inline formatting are a phase-1 foundation in the roadmap, but no competitor's users are asking redlines for bold/italic change detection; python-redlines already does it for DOCX. The block model matters far more than the inline model, and can be built first with inline attributes as an optional field.

The diff-match-patch study is worth doing but is a leaf-level concern; the missing algorithmic work is block alignment and move/split/merge detection, which diff-match-patch does not address at all.

## 9. A suggested sequence

The following is a plan, not a commitment; each phase is independently shippable and the first two are small.

**Phase 0, spine hygiene (days).** Expose and default `autojunk=False`, or at least document the cliff. Add a post-pass that merges adjacent operations separated only by punctuation tokens (a minimal semantic cleanup). Make sentence mode preserve paragraph boundaries. Pull the 18 failing documents from the `neurotic_docx_bench` run logs and find out why. Add a regression corpus that includes a repetitive-schedule case. Release as 0.6.x.

**Phase 1, block model and readers (weeks).** Introduce the block tree dataclasses and a plain-text reader that recognises paragraphs, common numbering patterns (1., 1.1, (a), (i), Article, Section, Schedule) and markdown headings and lists. Keep the existing string API untouched: the current processors become the degenerate case of a tree with one block per paragraph. Ship the model with a JSON schema v2 that nests inline changes under block changes.

**Phase 2, alignment (weeks).** Implement exact, label, fuzzy and positional alignment with configurable thresholds; then moves, then split/merge, then renumbering. Build an evaluation corpus of before/after pairs with known ground truth (contract amendments, bill versions, LLM edits) and measure alignment precision against Word Compare and python-redlines as baselines. The 763 `base.docx`/`next.docx` pairs in `neurotic_docx_bench` are a ready-made starting corpus (AGPL-3.0, so usable for evaluation but not for bundling), and extracting their text through the benchmark's own adapter gives a like-for-like comparison with the published redlines 0.6.1 run. The benchmark's metric is visual, though; a structural redliner needs an *alignment* metric (did block X map to block Y, was the move found), which does not exist yet in the field and is itself a publishable contribution. This is the phase that makes or breaks the thesis; it deserves the most design care and the least code before the corpus exists.

**Phase 3, renderers and summary (weeks).** Rewrite markdown, rich and JSON over the tree; add the LLM change summary renderer and section-level statistics; make `redlines compare a.md b.md --by clause` the headline CLI.

**Phase 4, DOCX in and out by delegation (weeks).** Add a DOCX reader via python-docx (or adeu's projection) rather than a bespoke parser; add a DOCX writer that emits an edit batch for adeu or superdoc-redlines, with a native OOXML revision writer as a later option once the change tree is stable.

**Phase 5, agent surface (ongoing).** A `verify` command that checks an edited document against instructions (only these blocks changed, nothing moved, numbering intact); an MCP server exposing compare, summarise and verify; a skill file. This is where adeu's distribution playbook is worth copying directly.

## 10. Open questions worth deciding early

Whether the block model should try to be a superset that DOCX, markdown and Akoma Ntoso all map into, or a minimal core with per-format extensions. The former is tempting and is how projects grow OOXML-shaped; the latter is closer to redlines' character.

Whether to depend on `rapidfuzz` (as adeu does) for alignment similarity, or stay stdlib. Alignment quality will probably justify one small dependency; the zero-dependency story is worth less than good alignment.

Whether a native DOCX revision writer is ever needed, or whether delegation to appliers is the permanent answer. The market seems to be converging on "one deterministic OOXML patcher per stack"; adding a fourth is low value unless the others stall.

Whether to reach out to JSv4 and Dealfluence before building. Both projects have an obvious hole exactly where redlines is strong (a readable, format-neutral change model), and both are the natural readers and writers for it.

## Sources

Current codebase: `redlines/redlines.py`, `redlines/processor.py`, `redlines/document.py`. Superseded planning material, from a working checkout and not part of this repository (see the note in section 2): `.planning/PROJECT.md`, `.planning/ROADMAP.md`, `.planning/REQUIREMENTS.md`, `.planning/research/SUMMARY.md`, `.planning/research/FEATURES.md`. Autojunk and cleanup behaviour verified by running the tokeniser and `SequenceMatcher` on synthetic inputs, 26 August 2026.

superdoc-redlines and SuperDoc: https://github.com/yuch85/superdoc-redlines (README, package.json, SKILL.md, src/wordDiff.mjs, src/editorFactory.mjs); https://skills.rest/skill/superdoc-redlines; https://github.com/superdoc-dev/superdoc; https://www.superdoc.dev/changelog/2026-03-22-document-engine; https://docs-v1.superdoc.dev/document-engine/diffing; https://docs.superdoc.dev/document-api/reference/diff; https://pypi.org/project/superdoc-sdk/; https://registry.npmjs.org/superdoc-redlines (404).

python-redlines and Docxodus: https://github.com/JSv4/Python-Redlines; https://pypi.org/project/python-redlines/; https://github.com/JSv4/Python-Redlines/issues/16, /issues/13, /issues/8; https://github.com/JSv4/Docxodus; https://raw.githubusercontent.com/JSv4/Docxodus/main/docs/architecture/ir_diff_engine.md; https://raw.githubusercontent.com/JSv4/Docxodus/main/docs/architecture/wml_comparer_gaps.md; https://redlines.opensource.legal/; https://pepy.tech/projects/python-redlines; https://pypi.org/project/docx-scalpel/; https://www.ericwhite.com/blog/2016/08/25/introducing-wmlcomparer-a-module-in-open-xml-powertools/.

adeu: https://github.com/dealfluence/adeu; https://raw.githubusercontent.com/dealfluence/adeu/main/README.md; https://raw.githubusercontent.com/dealfluence/adeu/main/docs/FIDELITY.md; https://github.com/dealfluence/adeu/issues; https://pypi.org/project/adeu/; https://registry.npmjs.org/@adeu/core; https://pepy.tech/project/adeu; https://adeu.ai/news/adeu-launch-announcement; https://adeu.ai/docx-benchmark; https://legal-oss.com/projects/dealfluence/adeu.

neurotic_docx_bench and the 2026 cohort: https://github.com/jandira-tech/neurotic_docx_bench (README.md, RESULTS.md, bench.yaml, src/neurotic_docx_bench/redlines_gen.py); https://redlines.free/ (jubarte); https://github.com/stemma-sh/stemma; https://github.com/UseJunior/safe-docx; https://github.com/JSv4/Docxodus.

Landscape: https://pypi.org/project/redlines/; https://pepy.tech/projects/redlines; https://libraries.io/pypi/redlines; https://github.com/google/diff-match-patch; https://github.com/diff-match-patch-python/diff-match-patch; https://github.com/anubhabb/diff-match-patch-rs; https://github.com/kpdecker/jsdiff; https://github.com/Shoobx/xmldiff/blob/master/CHANGES.rst; https://github.com/officedev/open-xml-powertools; https://github.com/Wilfred/difftastic; https://github.com/prosemirror/prosemirror-changeset; https://tiptap.dev/docs/tracked-changes/getting-started/overview; https://www.draftable.com/rest-api; https://help.draftable.com/hc/en-us/articles/Release-Notes-Draftable-Legal-February-March-2026-v26-2-0-v26-3-0; https://www.harvey.ai/blog/improved-word-experience; https://complexdiscovery.com/microsoft-puts-legal-agent-inside-word-sharpening-contract-review-competition/; https://knightli.com/en/2026/04/04/analyze-docx-agent-skill/ (Anthropic docx skill); https://github.com/SecurityRonin/docx-mcp; https://github.com/AnsonLai/docx-redline-mcp; https://github.com/evolsb/legal-redline-tools; https://www.monperrus.net/martin/tree-differencing; https://www.researchgate.net/publication/376439724_Comparative_Prints_Suite_of_the_United_States_House_of_Representatives_NLP_for_Tracking_Changes_in_Bills_and_Laws; https://help.lawmaker.legislation.gov.uk/help/live/what-s-new-in-version-10.
