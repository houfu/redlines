# ADR-0033: The change-tree wire format

**Status:** Accepted
**Date:** 2026-09-05
**Amended:** 2026-10-18 -- the block trees are optional on the wire. See *Amendment* below.
**Amended:** 2026-10-18 -- a deletion is placed, and counted, in its own parent. See the second *Amendment* below.
**Deciders:** houfu

## Context

[ADR-0011](0011-json-canonical-annotated-renderer.md) decided that JSON is the canonical change format, with a published schema, a top-level `schema_version` and a compatibility policy: additive changes bump the minor, breaking changes bump the major and the previous major stays producible. It did not say what is *in* the JSON. [ADR-0012](0012-html-like-addresses.md) and [ADR-0029](0029-address-syntax.md) settled how a block is addressed; [ADR-0005](0005-minimal-core-open-semantic-layer.md) settled roles and spans; [ADR-0030](0030-matched-by-and-confidence.md) settled how a *reader* reports its own certainty and reserved the same two field names for alignment to use on a different object. What remains is the shape of a change node, the topology of the change list, and where the entry point that produces all of it lives.

Three things make this urgent rather than incremental. ROADMAP § M2 lists "JSON schema frozen" as a milestone exit criterion, so the format is committed to before M3's renderers, M4's site or M5's MCP tools have consumed it. The MCP server is a separate package ([ADR-0017](0017-separate-mcp-package.md)) that reads this format across a package boundary. And the site is a browser build that consumes it with no adapter layer available to absorb a mistake. A field added here in the wrong shape is cheap; a field removed later is not.

One inherited claim has to be corrected in the same breath. `redlines/pipeline.py`'s module docstring says M2's compare pipeline "belongs here, next to this function", while the same file says `read_document` is deliberately not re-exported and should be imported by its full path. PRD § 9 wants `compare` to be the headline public API, imported as `from redlines import compare`. A re-exported function inside a deliberately-not-re-exported module would make that module half-public, which is a worse outcome than moving a sentence.

## Decision

### Where `compare()` lives, and what a string means

`compare()` lives in a new `redlines/comparison.py`, alongside `Comparison`, `ComparisonConfig`, `SCHEMA_VERSION` and `comparison_schema_text()`, and `redlines/__init__.py` gains exactly one star-import line for that module. The aligner is `redlines/alignment.py`, backend selection is `redlines/similarity.py`, the change tree is `redlines/changes.py`, and `filters.py` and `statistics.py` consume it. `redlines/pipeline.py`'s docstring is edited in the same change to point at `redlines.comparison` rather than at itself. M4's `verify()` ([ADR-0015](0015-verify-mode-in-1-0.md), R24) lands in this module beside `compare`.

**A bare `str` argument is always content, never a path.** The library does not stat the filesystem behind the caller's back: a one-line contract string must never turn into a file read because it happens to name a file on the server's disk. Reading files is what `Document` and `PlainTextFile` already exist for, so accepting a `Document` covers the file case with no new semantics and keeps the [ADR-0003](0003-compatibility-facade.md) facade types load-bearing. The CLI keeps its own path resolution, which is where [ADR-0025](0025-cli-as-thin-skin.md)'s shared argument layer will hold it. `source_path` and `test_path` are **name hints for format detection only**, mirroring `read_document(..., path=...)`.

**Format detection is per side.** When `format` is omitted, each side is detected independently from its path hint or its content; if the two detected formats differ, `compare()` raises `ValueError` naming both, rather than silently picking one. `ComparisonConfig.source_format` and `.test_format` stay separate fields, so a comparison always records what each side was actually read as.

### The alignment is public, and optional on the wire

`Comparison` carries five fields: `source`, `test`, `alignment`, `changes`, `config`. **`Comparison.alignment` is public and first-class**, because an unchanged matched pair produces no change node, so the correspondence set — the thing the benchmark scores — is not expressible in the change tree at all. That is a public API consequence of [ADR-0021](0021-alignment-benchmark.md) existing, and it is settled now, before M5 starts reading the object.

On the wire it is an **optional top-level key**, emitted only under `to_dict(include_alignment=True)`. The full pair list roughly doubles a large payload for data that only the benchmark reads today, and the schema declares it optional, so turning it on by default later is not even a minor bump.

`ComparisonConfig` embeds `AlignmentConfig` **whole** rather than re-flattening passes and thresholds beside it: one source of truth, so adding a knob in [ADR-0032](0032-alignment-passes.md) needs one edit rather than two and the two halves cannot drift on a threshold name. `ComparisonConfig.processor` is `type(processor).__name__` — a name, not a serialised object — and passing a custom `RedlinesProcessor` is supported in 1.0, since the leaf differ is pluggable per R17.

### The change node

Five kinds: `insert`, `delete`, `modify`, `move`, `renumber`. `split` and `merge` are **not** members of the enum in 1.0 — a consumer switching exhaustively should not have to handle a value nothing produces — but are reserved as a documented constant and named in the schema's `description`, so adding them in 1.1 ([ADR-0009](0009-moves-before-splits.md)) is an additive minor bump with the enum widened.

**Kind precedence when more than one is true is `move > renumber > modify`.** No information is lost, because every node carries both addresses, both labels and its inline ops regardless of which kind won. This is a deliberate clarification of the M2 decisions record's D-4 shorthand ("inline ops nested only under `modify`"): read literally, a block that is both renumbered and edited would win kind `renumber` and carry no inline ops, silently losing the text edit. `inline` therefore nests under `move` and `renumber` nodes too, not only `modify` — D-4's phrasing describes *where* inline ops nest (inside a change node, never as a sibling list of their own), not which kinds may carry them.

Every node carries:

| Field | Notes |
|---|---|
| `source_address`, `test_address` | **both, on every node**, not only on `move`/`renumber`. `None` on `insert` and `delete` respectively |
| `block_kind` | the affected block's structural kind |
| `source_label`, `test_label` | |
| `role` | **single-valued**, from the test block, or the source block on a delete |
| `span_types` | the types of spans the change **touched** — sorted, deduplicated |
| `matched_by` | the alignment pass name, or `"unmatched"` on insert and delete |
| `confidence` | the alignment confidence; `0.0` for `unmatched` |
| `source_text`, `test_text` | the affected block's own text on each side |
| `inline` | `InlineOp` tuple; only ever non-empty on `modify`, `move` or `renumber` (see the kind-precedence note above on why `move`/`renumber` carry it too) |
| `breadcrumb` | the ADR-0029 heading breadcrumb, test side, precomputed |

Both addresses are on every node because a `modify` inside a moved clause genuinely has two — the sample pair has exactly one such node — and a format where only `move` carried both would force that node to lie about one of them.

`span_types` reads [ADR-0005](0005-minimal-core-open-semantic-layer.md)'s word strictly: for a `modify`, the types of spans on either block that **overlap an inline op**; for an `insert` or `delete`, all span types on the block. The sample pair shows why. Clause 9.2 carries `party` spans at `[4:10]` and `[77:85]` and a `cross_reference` at `[164:167]`, and its single inline op replaces `src[164:168]`. Under "touched", `span_types == ("cross_reference",)` — precisely the "cross-reference updated to follow the renumbering" signal PRD § 3a promises. Under "every span on the block" it would also carry `party`, and the signal would be buried. Span *values* are not copied onto the node; the blocks at both addresses are in the same payload.

`InlineOp` carries **character offsets into each block's own text**, not token indices: it is the frame `Span` already uses, so "which spans did this touch?" is an interval overlap and nothing more; M3's CriticMarkup renderer splices by character; and R27a's tuple becomes exact rather than approximate. v1's token positions stay in v1, untouched. The opcode-to-inline-op conversion currently inlined in `Redlines.changes` is extracted into a free `redlines_from_opcodes()` in `changes.py` rather than reimplemented, per ADR-0010's reuse rule, and M3's facade then uses the same function.

**Every ratio on the wire is rounded to four decimal places at the serialisation boundary**, with full precision kept for internal comparisons. ADR-0008 already notes that results differ subtly with and without rapidfuzz; rounding stops the golden change tree churning on a 1e-9 backend difference while leaving a real difference visible.

Three derived numbers are accessors on `Change`, computed rather than stored, and defined exactly so that the filter and the statistics cannot disagree:

- `chars_added = sum(len(op.test_text) for op in inline)`
- `chars_deleted = sum(len(op.source_text) for op in inline)`
- `tokens_changed = sum(len(tokens(op.source_text)) + len(tokens(op.test_text)) for op in inline)`, using the same tokeniser the leaf differ used.

### The topology: flat, document-ordered, topmost wins

**`ChangeTree.changes` is a flat tuple in document order.** The "tree" is the addresses, which already encode the hierarchy exactly, plus the inline ops nested under a node — the only nesting R18 mandates. R39 names the deliverable a block-change list; ADR-0029 already settled that a prefix match is enough for scope, so filtering by section is a string test on a flat list rather than a question about whether to keep unmatched ancestors. The sort key is `(test address or predecessor, source address, kind index)` with `kind index` following the declared kind order, and no two changes may share a full sort key.

**Granularity is topmost-wins for `insert`, `delete` and `move`**; `modify` and `renumber` are always per block. One node for the topmost inserted block is what makes an inserted table row come out as a single row-level `insert` by construction rather than by a table special case. A descendant of a move that also changed gets its own `modify` or `renumber` carrying both addresses, and is not additionally reported as a move — **the same rule the benchmark scores moves under**, so engine and metric agree by construction rather than by coincidence.

**An address shift alone is never a change.** When a row is inserted above it, the "Go-live sign-off" row moves from `row[5]` to `row[6]` and nothing is emitted. When a clause is renumbered its address shifts *and* its label changes, and the label is what makes it a `renumber`. This one rule is what keeps a single insertion from producing a hundred nodes.

Consequently, statistics count **change nodes**: a deleted 40-block schedule is one `deleted`, not 40. That is documented on the fields, and a consumer wanting block counts walks the subtree in the block tree, which is in the same payload.

**No derived old→new label index in 1.0.** It is exactly derivable from the `renumber` nodes in the same document, and ADR-0011 makes adding it later a minor bump. Every field in a format frozen this early is a maintenance cost.

### Filters

`ChangeFilter` is a frozen dataclass with `to_dict`/`from_dict`, not a bag of keyword arguments, because the same specification has to be a CLI flag set, an MCP tool argument, M4 verify's `allowed` scope and a record on the wire — and kwargs alone get re-parsed in four places, which is the drift ADR-0025 exists to prevent. An empty field is no constraint; fields AND together; values within a field OR.

- **Address prefixes are segment-aligned**: a prefix matches if `addr == p` or `addr.startswith(p.rstrip("/") + "/")`. A naive `str.startswith` makes `/section[1]` match `/section[11]`, and both exist in the sample pair — so verify's scope would silently leak. `"/"` matches everything. A prefix is tested against **either** address, so a block moved out of a scoped section is still reported by a scope naming its old location.
- **`min_chars` is in changed characters**, compared against `max(chars_added, chars_deleted)` for the node, so the filter and the statistics use one definition. Characters because v1's `Stats` already counts characters and "at least 20 characters" is a threshold a person can picture. `min_chars > 0` therefore drops renumbers, which is the "show me the substantive edits" behaviour people ask for.
- **`has_inline`** exists because kind precedence makes a renumbered-and-edited clause a `renumber` node, so a consumer filtering on `kind == "modify"` would miss its edit.

**A filtered comparison keeps the same shape**: the same two block trees unpruned, the same alignment, a filtered change list, and `config.filter` set to the spec that produced it. So `to_dict()` validates against the same schema with no conditional branches, and the M3 renderers need no filtered code path. Recording the filter is the honesty requirement — a filtered payload that looks like a full comparison is a trap for an agent.

### Statistics

Counts, plus one row per **section block that has a `heading` child**, with every change attributed to its **nearest enclosing** section only, so nothing is double-counted. Density is changes over blocks in that section, from the unfiltered trees: filtering changes numerators only.

**This is a deliberate reinterpretation of [#139](https://github.com/houfu/redlines/issues/139)'s "per top-level section", and it is recorded here rather than discovered in the schema.** Read literally against the real tree it produces four rows, one of which — `/section[1]` — holds the entire body of the agreement, eleven numbered sections and a hundred-odd blocks, and reports one density number that says nothing. Under the rule above, `/section[1]` reports only its title and parties paragraph and `/section[1]/section[3]` reports the renumbering as 1 insert plus 2 renumbers over 6 blocks, density 0.5 — the number a reviewer actually wants. #139's own next clause, "using the heading breadcrumb from ADR-0029", is what its "top-level" phrasing was pointing at.

There is no `by_block` array. R22's per-block half is `len(change.inline)`, the op kinds and the three derived numbers, all already on the node; a second array keyed by address would be a second copy of the change list, which M5's size guards and the site would both pay for.

### The schema, and what R27a is

**One file, `redlines/schemas/comparison-v2.json`, draft-07**, matching both existing schemas, with `$id: https://houfu.github.io/redlines/schemas/comparison-v2.json`. `definitions` carries `blockTree`, `block`, `span`, `dropped`, `change`, `inlineOp`, `alignment`, `alignedPair`, `alignmentConfig`, `changeCounts`, `sectionStatistics` and `changeFilter`. **The block tree is a section of this schema, not a second file**, and M5's `read_blocks` is documented as producing `comparison-v2.json#/definitions/blockTree`. A two-file split needs a cross-file `$ref` to a URL that does not resolve until M4 publishes the site — a trap in tests and an offline failure for the MCP server — plus two version numbers to keep in step. A JSON Pointer into one published file gives the block tree a citable identity at no cost.

`schema_version` is the **string `"2.0"`**: two components because ADR-0011 defines exactly two kinds of change, and a string because an integer `2` could not distinguish a 2.1 payload from a 2.0 one. ADR-0011's policy is restated on the field's `description` and in the module docstring, so a consumer reads it where they are working. `Comparison.from_dict` rejects a different major with a clear message, accepts an equal-or-lower minor, and rejects a *higher* minor rather than silently dropping fields — consistent with the block model's existing strictness, which would otherwise reject the unknown keys with a confusing error. `SCHEMA_VERSION` and `comparison_schema_text()` mirror `profile_schema_text()`, and the schema's own constant for the version is drift-tested against `SCHEMA_VERSION` the way ADR-0028 drift-tests the profile schema. Unlike the profile schema, this one is validated with the real `jsonschema` package against real output, which is a **dev-only** dependency and never an extra: the blocking Pyodide job builds a plain wheel and imports it.

The `source` and `test` sections are **byte-for-byte `BlockTree.to_dict()`**. M1's serialisation is not reshaped, which keeps the existing expected trees valid as-is, keeps `BlockTree.from_dict` usable on a slice of a v2 document, and gives ADR-0030's required fields to every consumer with no adapter. The raw document strings are *not* carried: the block trees already hold every character, and duplicating a 100-page contract triples the payload M5 and the site have to move.

**R27a ships as a test, not an export.** [#140](https://github.com/houfu/redlines/issues/140) says so in as many words: not an export, proof that one is possible. The recovery is one small readable function in `tests/test_recoverability.py` that 1.1's applier lifts into `redlines/apply.py` when R26 arrives. A public helper now would freeze a surface before the consumer that shapes it exists.

**An M4 obligation, recorded here.** ROADMAP § M0 claims a `/schemas/` location was stood up on the site. It was not: `site/public/` holds only `api/` and `favicon.svg`. M2 ships the in-package file with `$id` set to the URL M4 will publish it at, and **M4 must create `site/public/schemas/` and copy `comparison-v2.json` (and `profiles/schema.json`) into it.** The two older schemas use a GitHub blob URL as `$id`, which is not a resolvable schema URL; they are left frozen rather than retrofitted.

## Amendment, 2026-10-18: the block trees are optional on the wire

The *Revisit when* section below said that if payload size ever became the constraint, the first thing to reconsider was carrying both full block trees by default, not the change list. It became the constraint before M5 started, and the measurement is the reason to act before the freeze lands rather than after.

On the section 3a sample pair — two 9 KB documents, 102 and 103 blocks, ten change nodes — `to_dict()` without the alignment is about 137 KB compact. The `source` and `test` trees are 62 KB and 63 KB of that; `changes` is under 7 KB and `statistics` 5 KB. Claude Code writes any MCP tool result over 50,000 characters to a file and hands the model a path instead; Codex truncates tool output to a per-tool token budget. A model-facing `compare` tool returning the default document would therefore never be read inline, even on a two-page contract. The change list, which carries both addresses and both texts on every node by the decision above, is self-sufficient for that reader.

So: **`source` and `test` leave the schema's `required` list.** `to_dict()` still emits them by default — nothing a current consumer reads changes — and `to_dict(include_trees=False)` writes the **compact form**: `schema_version`, `config`, `changes`, `statistics`, and `alignment` if asked for. The compact form validates against the same file. The two keys are present together or absent together. `from_dict` refuses the compact form with a message naming `include_trees=True`, as it already refuses a payload without its alignment. `statistics.source_blocks` and `statistics.test_blocks` already carry the block counts, so the sentence in the Decision about walking the subtree for block counts holds when the trees are present and degrades to the statistics when they are not.

Why now and not as a 2.1: loosening `required` is a breaking change for a consumer that validates strictly and assumes the keys, which is exactly what ADR-0011 says a minor bump may not do. Done before the schema is published anywhere, it is part of the 2.0 freeze; done after, it is a 3.0. The model-facing consumers that need the compact form — the M5 tools as read by Claude Code and Codex, and the MCP App that pulls the full document through its own channel — are the reason the freeze happens against a real client, which is ADR-0020's argument for building the server before the site.

## Amendment, 2026-10-18: a deletion sits in its own parent, and is counted there

*The topology* says the change list is in document order, with a sort key whose first element is a node's "test address or predecessor". It never defined the predecessor of a delete. M2's builder took the last source block before the delete, in pre-order, that has a counterpart, and a block that has moved away counts. So a deletion that follows a moved block is listed after that block's *destination*, in another section. Across the 60 committed runs (every source and test pair in the repository, 59 distinct pairs with the sample pair's text twin run twice), that misplaces 1 of the 69 delete nodes, in `govinfo-hr7385-ih-to-eh`.

`statistics()` has a defect of the same family. It looks up a delete's nearest enclosing *source* section address in rows keyed by *test* section addresses. On `govinfo-hr4668-ih-to-rh`, `statistics()` and `to_dict()` raise `KeyError: '/section[6]/section[1]'`. Where the address happens to exist, the answer is silently wrong: with `## 1A. Extra` inserted above `## 2. Terms`, the deletion of clause 2.2 is counted under "1A. Extra".

Both are produced values in a format frozen at 2.0, where only additive changes are allowed. They are corrected now for the reason the first amendment gives. 0.6.2 is the latest release and the latest tag, so no v2 output exists outside the repository, and the window closes when M4 publishes `/schemas/`. Done before publication, the correction is part of the 2.0 freeze; done after, it would be a breaking change. `schema_version` stays `"2.0"`.

Measured on the 60 runs:

- **Placement** reorders one run. In `govinfo-hr7385-ih-to-eh`, delete index 6 moves from after node 5 to after node 20. No golden changes, the order of `statistics.sections` is unchanged, and no benchmark number moves, because `benchmark/score.py` reads only moves and renumbers.
- **Attribution** stops `statistics()` and `to_dict()` raising on `govinfo-hr4668-ih-to-rh`, and changes one other run: in `govinfo-hr7385-ih-to-eh`, one delete moves from the "2d Session" row to "AN ACT", where its parent's counterpart is and where the renderers draw it. The other 58 runs are identical, the sample pair included.

**Placement.** A delete sits in its own parent, after its nearest preceding sibling that stayed in place. The anchor, in `redlines/changes.py`:

```python
@dataclass(frozen=True, slots=True)
class Anchor:
    test_parent: str        # test counterpart of the block's source parent
    after: str | None       # a child of test_parent; None means "first in test_parent"

class Anchors:
    def __init__(self, *, source: BlockTree, test: BlockTree, alignment: Alignment) -> None: ...
    def place(self, source_path: str) -> Anchor | None: ...
```

1. `moved = {p.source_path: p.test_path for p in alignment.pairs if p.moved}`.
2. An *own move* is a source path `s` in `moved` for which `under_a_move(s, moved[s])` is false.
   - `under_a_move(s, t)` walks `s`'s source ancestors `a`, and is true when `a` is in `moved` and `t` is at or under `moved[a]`.
   - This is `_Builder._under_a_move`, lifted to a module-level function that both use.
   - The own moves are exactly the sources of the change list's `move` nodes: 24 of 24 on the 60 runs.
3. For each source block `P`, with `TP = alignment.test_for(P.path)`, set `last = None`. Then, for each child `X` of `P`, in order:
   - `anchor[X] = None if TP is None else Anchor(TP, last)`;
   - then, if `TP is not None`, and `T = alignment.test_for(X.path)` is not `None` ("X has a counterpart"), and `X` is not an own move, and `parent(T) == TP`: set `last = T`.
4. `place(X) = anchor[X]`. This is one pass over every parent's children, O(N): 1.1 ms for 2,000 blocks with 1,000 deletes.
5. A topmost delete's parent is always matched, so its anchor is never `None`. A move origin's anchor is `None` only inside a deleted ancestor.
6. **Meaning.** X sits immediately after the whole test subtree of `after`. When `after` is `None`, X sits immediately after TP's own block and before TP's first child; when TP is `/`, that means before the first block.
7. **The sort key, rewritten.** This replaces the key given in *The topology*. Each node's key is `(rank, after, source_rank, kind_rank)`.
   - A node with a test address: `rank` is that address's test pre-order index, and `after` is 0.
   - A delete: `(rank, after) = (t_last(Anchor.after), 1)`, or `(t_order(Anchor.test_parent), 1)` when `Anchor.after` is `None`. Here `t_order(b)` is `b`'s own test pre-order index, and `t_last(b)` is the pre-order index of the last block in `b`'s test subtree.
   - `source_rank` is the source pre-order index (−1 for an insert). `kind_rank` is the index in `CHANGE_KINDS`.
   - No two nodes share a key.
8. `statistics._section_order` orders whole-section deletes with the same anchor. `Anchor`, `Anchors` and the lifted `under_a_move` stay out of `changes.__all__`.

Five rules were tried on the 60 runs and on constructed cases. In *trailing insert*, section 3 gains a last clause and section 4 is deleted. In *moved predecessor*, clause 7.3 moves to section 8 and 7.4 is deleted. In *mirrored swap*, siblings A M D Z become A Z M.

| Rule | 60 runs | Trailing insert | Moved predecessor | Mirrored swap |
|---|---|---|---|---|
| **own parent, skipping own moves** (above) | 1 reordered | ✓ | ✓ | ✓, beside the siblings that stayed |
| nearest preceding block in the same move scope | 1 | ✗ §4 inside §3 | ✓ | ✓ |
| own parent, without the skip | 1 | ✓ | ✓ | ✗ follows the moved block |
| latest sibling in test order | 1 | ✓ | ✓ | ✗ after the arrival |
| M2's rule | 0 | ✗ | ✗ | ✗ |

A deleted child of a moved clause passes under every rule. It differs from M2's rule only in where a renderer draws it, inside the destination, and not in the order of the change list.

**Attribution,** in `redlines/statistics.py`:

- A delete whose own block is a section unit keeps its own row, as before.
- Any other delete counts under `_nearest_enclosing(Anchors.place(d).test_parent, test_parents, test_units)`: the test section that shows it.
- Every other node keeps its test-address attribution.

**Schema.** The `changes` property's `description` in `comparison-v2.json` gains "a delete sits in its own parent, after its nearest preceding sibling that stayed in place (ADR-0033, amendment)".

**Tests.** `tests/test_delete_anchor.py` covers the moved predecessor, a deleted child of a moved clause, a clause moved out of a moved clause, the trailing insert, a swap and the mirrored swap, first-child and before-first-block deletes, and the node order of `govinfo-hr7385-ih-to-eh`. `tests/test_statistics.py` gains `govinfo-hr4668-ih-to-rh`, which must not raise, and the constructed "1A" pair, whose deletion must count under "Terms". `tests/test_corpus_roundtrip.py` runs `statistics()`, `to_dict(include_alignment=True)` and `from_dict` over all 60 runs. The sample pair's change trees stay byte-unchanged, and `tests/test_benchmark_gates.py` stays green.

The renderers place deletions and move origins with the same anchor ([ADR-0037](0037-annotate-the-test-document.md)), so the annotated view and the change list agree on where every deletion sits.

## Alternatives considered

**A nested change tree mirroring the block tree.** Reads well for a renderer, and makes "a moved clause with an edit inside" one subtree. Rejected: it needs pass-through scaffolding nodes for unchanged ancestors — a modify three levels down needs three — and every consumer then has to distinguish scaffolding from a real change; filtering has to decide whether to keep unmatched ancestors, which is exactly the shape problem [#138](https://github.com/houfu/redlines/issues/138) asks to avoid. A consumer wanting a nested view builds one from the addresses in a dozen lines.

**A flat list plus derived `by_address` and `children_of()` accessors.** Best of both for Python callers at zero wire cost. Rejected as API surface designed before a consumer asked for it.

**One change node per affected block.** Statistics counts become literal block counts. Rejected: an inserted table row becomes four nodes, contradicting [#134](https://github.com/houfu/redlines/issues/134)'s stated bar, and a large deletion floods the list.

**Paired `source_role`/`test_role`, and a `spans_touched` list carrying each span's type and its old and new value.** The summary renderer could then say "cross-reference 3.3 became 3.4" with no lookup. Rejected: a fourth type to version in a format being frozen early, for information already present twice in the same document.

**A `subtree_blocks` integer on insert, delete and move nodes.** One integer, both counts. Rejected as derivable from the block trees in the same payload.

**`compare()` resolving filesystem paths for bare strings**, mirroring the CLI. Convenient at a REPL. Rejected: the library would stat the filesystem behind the caller, and it duplicates logic ADR-0025 puts in the shared argument layer.

**Two schema files** — `block-tree-v1.json` plus `comparison-v2.json` with a cross-file `$ref`. Cleanest for MCP resources. Rejected on the unresolvable-URL trap and two version numbers.

**`schema_version` as the integer `2`.** Impossible to get a minor bump wrong. Rejected: ADR-0011 defines a minor bump, so a consumer could not tell a 2.1 payload from a 2.0 one.

**`min_chars` measured in changed tokens.** Matches the differ's own unit and is stable across languages. Rejected: "at least five tokens" is not a threshold a user can picture, and v1's `Stats` already counts characters, so two units would coexist.

**Per-top-level-section statistics as #139 literally words it**, and **every section with own plus cumulative counts and a `by_block` array**. The first produces one meaningless density number for the body of the document; the second roughly doubles the statistics payload.

**Shipping `inline_edits()` as public API.** Rejected: #140 says it is not an export, and it would freeze a surface before R26 exists to shape it.

## Consequences

Positive: one payload carries both block trees, the change list, the statistics and the configuration in force, so every question a consumer has — what changed, where, under what settings, and what the surrounding document looks like — is answerable without a second call. The block-tree section is unchanged from M1, so M5's `read_blocks`, the site's block list and the MCP resources all get ADR-0030's reporting fields for free. Both addresses on every node make a moved-and-edited clause expressible honestly. Topmost-wins granularity is shared with the benchmark's scoring rule, so the engine and its own metric cannot disagree about what a move is. And the filter is a value that travels with the result, so a filtered payload cannot pretend to be a full one.

Negative: this is a large surface to freeze before its three main consumers exist. The flat list makes a nested view a consumer's job. `span_types` under the "touched" reading is more work to compute and depends on inline ops being right, so an off-by-one in the character offsets shows up as a missing semantic signal rather than as an obvious error — which is why the recoverability test asserts the offsets directly. The statistics section reinterprets its own issue's wording, and anyone reading #139 alone will find the code says something different. Rounding ratios to four places is a deliberate loss of information at the boundary. And the `$id` points at a URL that does not exist until M4 does the work recorded above, which is a promise this ADR is making on M4's behalf.

## Revisit when

If M3's renderers or M5's tools repeatedly rebuild a nested view from the addresses, that is the signal for derived accessors — in Python first, not on the wire. If a consumer needs the old→new label index often enough to write the one-line comprehension twice, add it as a minor bump. If splits and merges land in 1.1, widening `ChangeKind` and the schema's enum is the additive path this format was shaped to allow; if they need a different node shape instead, that is a major bump and its own ADR, not an edit to this one. If the payload size becomes the constraint M5's size guards suggest it might, the first thing to reconsider is carrying both full block trees by default, not the change list. And if a second producer ever emits this format, the "byte-for-byte `BlockTree.to_dict()`" clause stops being a convenience and becomes a conformance requirement worth testing directly.

## Related

ADR-0003, ADR-0005, ADR-0011, ADR-0012, ADR-0029, ADR-0030. Issues [#136](https://github.com/houfu/redlines/issues/136), [#137](https://github.com/houfu/redlines/issues/137), [#138](https://github.com/houfu/redlines/issues/138), [#139](https://github.com/houfu/redlines/issues/139), [#140](https://github.com/houfu/redlines/issues/140), [#144](https://github.com/houfu/redlines/issues/144).
