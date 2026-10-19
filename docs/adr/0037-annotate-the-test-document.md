# ADR-0037: Annotate the test document with CriticMarkup

**Status:** Accepted
**Date:** 2026-10-18
**Amended:** 2026-10-19 -- the choices the implementation fixed (#192 to #195). See *Amendment* below.
**Deciders:** houfu

## Context

[ADR-0011](0011-json-canonical-annotated-renderer.md) made an annotated-document renderer a first-class output beside the JSON: "the source document with changes marked in place, using CriticMarkup for text and markdown and a tag variant (`<ins>`, `<del>`, `<moved from="…">`) for HTML". Its Context illustrated a replacement as `{--thirty (30)--}{++sixty (60)++}`, and its Consequences left one thing open: the renderer "needs a defined escaping story for documents that already contain CriticMarkup-like syntax". R21a adds block roles, shown as prefixes. ROADMAP § 5.6 made the renderer a 1.0 Must, because the MCP `summary` and `annotate` tools lean on it. The same milestone owes R20's markdown and rich renderers over the tree. [ADR-0036](0036-redlines-facade.md) found that a renderer over a block tree cannot be byte-identical to 0.6, so those are new renderers with goldens of their own, and they can share one traversal with the annotated view.

Five facts shape the decisions below. "The 60 runs" means every source and test pair committed in the repository: the eight text cases under `tests/corpus/`, both twins of the sample pair, and the 50 benchmark pairs. That is 59 distinct pairs, because the sample pair's text twin is run twice.

**Source or test is a question of order, not of marks.** Inline marks are symmetric: accepting or rejecting an op gives the same text whichever document carries it. The choice decides only the order of blocks, where a moved block appears, and whose whitespace the unchanged runs carry. Walking the test document is what makes "accept every mark" reproduce the test document exactly.

**CriticMarkup cannot say "moved", cannot nest, and defines no escape.** It has five constructs: insert, delete, substitution, comment and highlight. A highlight cannot wrap a moved block that carries inline marks, because the marks would nest.

**Readers drop a label's punctuation.** `label_candidates` strips one trailing full stop and keeps no raw form, so `## 2. Definitions` reads back as label `2` and text `Definitions`. Guessing the full stop back reproduces all 176 lines of the sample pair's two test documents, and is wrong on `1 Background`.

**Marks leave residue.** The syntax head and the role prefix must sit outside every mark, or a list item or a heading stops parsing. Table cells must be marked one at a time, or the table stops parsing. So rejecting an inserted list item leaves `- [clause] `, and rejecting an inserted row leaves `|  |  |  |`. Without a rule for that residue, accepting every mark reproduces the test rendering on 56 of the 60 runs; with one, on 60 of 60. The rule removes 6 lines on the accept side and 33 on the reject side, across the 60 runs.

**Deletions need a place to stand.** An in-place view has to put a deleted block somewhere, and the change list placed one delete in 69 after a block that had moved away. [ADR-0033](0033-change-tree-wire-format.md)'s amendment of 18 October 2026 corrects the placement in the change list and gives the renderers the same anchor, so the view and the list agree on where every deletion sits.

## Decision

### One walk over the test document

Every in-place output on `Comparison` walks one view: the test document in pre-order, with the source blocks of deletions (*ghosts*) and the origins of moves (*tombstones*) placed where they stood, by the anchor of ADR-0033's amendment. Those outputs are the six legacy markdown styles plus `custom_css`, the CriticMarkup text and markdown variants, the HTML document view of [ADR-0038](0038-render-html-once-in-python.md), and rich. The view is private, in `redlines/renderers/_view.py`. ADR-0033's revisit clause puts derived accessors in Python first, and a public status can follow a consumer that asks for one.

```python
class BlockStatus(str, Enum):
    UNCHANGED = "unchanged"; INSERT = "insert"; DELETE = "delete"; MODIFY = "modify"
    MOVE = "move"; RENUMBER = "renumber"; ORIGIN = "origin"
    def __str__(self) -> str: return self.value     # 3.10 and 3.11+ format str enums differently

@dataclass(frozen=True, slots=True)
class ViewNode:
    status: BlockStatus
    block: Block                 # test block; the source block for DELETE and ORIGIN
    counterpart: Block | None    # source block of a matched test block
    change: Change | None        # the node owning the status; None for UNCHANGED and inside an INSERT/DELETE subtree
    children: tuple["ViewNode", ...]

def build_view(comparison: Comparison) -> ViewNode
```

The rules were checked on the 60 runs: the view's insert, delete and matched counts equal `len(alignment.inserted)`, `len(alignment.deleted)` and `len(alignment.pairs)` on 60 of 60, and its `MOVE` nodes are exactly the change list's `move` nodes on 60 of 60.

1. **Status comes from `comparison.changes` only.** Unmatched descendants of an `INSERT` node take `INSERT` with `change=None`. A matched descendant is a move into the inserted block and keeps its own node. A filtered comparison therefore renders the same test document with only its own nodes marked, which is what keeps ADR-0033's promise that renderers need no filtered code path; a view that read `alignment.inserted` would still mark the inserts of a modify-only filter.
2. **Ghosts** are the source blocks of `delete` nodes.
   - Each goes into the children of `Anchor.test_parent`, directly after the child whose block is `Anchor.after`, or first when that is `None`. Ghosts that share an anchor go in source order.
   - A ghost's children are its source children that are in `alignment.deleted`, recursively, plus a tombstone for each child that is the source of a `move` node. That child's anchor is `None`, because its parent is deleted.
   - A matched child that did not move on its own rides with an ancestor's move, and appears at its test position.
3. **Tombstones** (`ORIGIN` leaves) are added for every `move` node whose `Anchors.place` is not `None`, placed as a ghost is. That includes a clause that moved out of a moved clause: its tombstone sits inside the outer clause's destination.
4. **Drawing.**
   - The *note-bearing sets* (CriticMarkup, HTML and rich) draw only the tombstone at a moved block's origin. At its destination they draw its test subtree in place: descendant nodes in their own status, deleted descendants as ghosts, inner origins as tombstones.
   - The *whole-move sets* (the six legacy styles and `custom_css`) draw 0.6's picture. At the origin, the moved block's whole source subtree is struck, deleted and moved-out descendants included. At the destination, its whole test subtree is inserted, with no ghost drawn inside it. A descendant that moved out is also inserted at its own destination.
5. **Tables, rows and cells** are view nodes, and renderers emit a table as one unit. A move origin among table rows cannot occur under [ADR-0032](0032-alignment-passes.md)'s default `move_kinds` (`paragraph`, `list_item`, `heading`) and was seen 0 times in the 60 runs. A renderer skips one if a custom `AlignmentConfig` produces it.
6. **Cost.** O(N), with path dictionaries built once and no `BlockTree.block_at` inside a loop: 1.1 ms for the anchors and 9 ms for the view and a render at 2,000 blocks. Nothing iterates over a `set`.
7. **Inputs.** The view reads only fields that survive `to_dict(include_alignment=True)` and `from_dict`, so a round-tripped comparison renders to the same bytes.

**Nested moves.** A tombstone stands for the moved block alone, and nothing of its subtree is drawn at the origin. Its descendants are drawn at the destination: matched descendants in their own status, deleted descendants as ghosts, and a descendant that moved out on its own as its own tombstone *inside the destination*, at its source position among its siblings, which is where `Anchors.place` puts it. Constructed case: clause 7.2 moves to 8.2, and its child (b) moves on to 9.2. The annotated view writes `{>>7.2 moved to 8.2 …<<}` in section 7; then, in section 8, 8.2, then (a), then `{>>(b) moved to 9.2 …<<}`; then (b) in place at 9.2. The legacy styles strike 7.2, (a) and (b) together at the origin, so their reject side stays in source order.

### Marks

| Output | Move | Renumber |
|---|---|---|
| the six legacy styles and `custom_css` | 0.6's picture: the whole source subtree struck at the origin, the whole test subtree inserted at the destination (rule 4) | `DEL("OLD ")INS("NEW ")` before the text |
| CriticMarkup | the destination in place with its edits, plus ` {>>moved from SRC_LABEL SRC_ADDRESS<<}`; at the origin, a line `{>>SRC_LABEL moved to TEST_LABEL TEST_ADDRESS<<}` | `{~~OLD~>NEW~~} ` as the label part |
| HTML document view | `data-kind="move"` plus a visible note; at the origin a `<p class="redlines-note">` ([ADR-0038](0038-render-html-once-in-python.md)) | `<span class="redlines-label"><del>OLD</del><ins>NEW</ins></span>` |
| HTML change list | one row, `OLD → NEW` and `SRC → TEST` | one row, `OLD → NEW` |
| rich | in place, plus a magenta note; a magenta tombstone line | old label `strike red`, new label `green` |

A replacement inside a block is `{~~OLD~>NEW~~}` in CriticMarkup; every other set writes a delete, then an insert. A modified or inserted fenced code block carries its marks *inside* the fence, in every output. The legacy styles cannot say "moved", so they draw a move as 0.6 does. The note-bearing sets say "moved" exactly when the change list does ([ADR-0009](0009-moves-before-splits.md)). One construct per `InlineKind` keeps the annotated text a lossless encoding of the test text plus its ops.

The mark sets, in `redlines/renderers/_marks.py`:

| Set | insert | delete | replace | notes | escape | moves |
|---|---|---|---|---|---|---|
| `red_green` | `<span style='color:green;font-weight:700;'>`…`</span>` | `<span style='color:red;font-weight:700;text-decoration:line-through;'>`…`</span>` | del + ins | none | none | whole |
| `none` | `<ins>`…`</ins>` | `<del>`…`</del>` | del + ins | none | none | whole |
| `red` | `<span style='color:red;font-weight:700;'>`…`</span>` | as `red_green` | del + ins | none | none | whole |
| `ghfm` | `**`…`**` | `~~`…`~~` | del + ins | none | none | whole |
| `bbcode` | `[b][color=green]`…`[/color][/b]` | `[s][color=red]`…`[/color][/s]` | del + ins | none | none | whole |
| `streamlit` | `**:green[`…`]** ` | `~~:red[`…`]~~ ` | del + ins | none | none | whole |
| `custom_css` | `<span class='{ins_class}'>`…`</span>` | `<span class='{del_class}'>`…`</span>` | del + ins | none | none | whole |
| `critic` | `{++`…`++}` | `{--`…`--}` | `{~~`…`~>`…`~~}` | `{>>`…`<<}` | the backslash rule below | in place, with notes |
| `html` | `<ins>`…`</ins>` | `<del>`…`</del>` | del + ins | elements | `html.escape` | in place, with notes |
| `rich` | style `green` | style `strike red` | del + ins | style `magenta` | none (`Text.append`) | in place, with notes |

The trailing spaces of the `streamlit` delimiters are 0.6's. The legacy styles copy document text verbatim, as 0.6 does, so a caller who renders untrusted input as HTML must sanitise it, and the docstring says so.

**The inline splice**, in `redlines/renderers/_inplace.py`:

```python
@dataclass(frozen=True, slots=True)
class Segment:
    kind: Literal["equal", "insert", "delete", "replace"]
    source_text: str
    test_text: str

def inline_segments(change: Change) -> tuple[Segment, ...]
```

- Ops are taken in order. An `equal` segment carries both sides' text.
- Joining every segment's `test_text` gives `change.test_text`, and likewise for the source side.
- Renderers emit an `equal` segment's `test_text`.
- In a CriticMarkup substitution only, whitespace common to the end of both sides is emitted after the mark: `{~~four~>two~~} hours`. Every other mark, and every legacy style, keeps its whitespace inside, which is 0.6's token convention.
- The function is package-private.

**Line syntax.** The markdown variant takes it from the block's `attrs`:

- a heading is `"#" * attrs.get("atx_level", min(level + 1, 6)) + " "`;
- a list item with `list_marker` is `"    " * (list_depth - 1) + list_marker + " "`, and each nested list item is its own line with its own head;
- a fence is as the grammar below gives it;
- a quote has `> ` before every physical line.

The text variant has no line syntax. The six legacy styles follow the document's format. An inserted or deleted row whose cells are all empty is marked on its first cell with an empty mark (`{++++}`, `<ins></ins>`), so that it stays visible. The output is a normalised document, not the input bytes: the readers have already re-joined hard wraps, a no-break space becomes a space, and a setext heading comes out as ATX.

**Tables, separators and whitespace.**

- Order: the header row, then the alignment row (markdown variant only, from the table's `alignments`: `---`, `:---`, `---:`, `:---:`), then the data rows, each `| c1 | c2 |`, joined by `\n`.
- Ghost rows whose anchor's `after` is `None` go after the alignment row in the markdown variant and after the header row in the text variant, so that a deleted row never becomes the rendered header. A wholly deleted table writes its first ghost row as its header.
- A mark never spans a `|`. An inserted or deleted row marks each non-empty cell; a modified cell is spliced inside the cell.
- A `|` in cell text is written `\|` in both variants.
- Blocks are joined by `\n\n`, with no trailing newline. A whitespace-only difference produces no node and no mark.

### The CriticMarkup grammar

There are no spaces inside delimiters. The CriticMarkup specification allows `{++ x ++}`; this grammar never emits it.

```
insert                {++TEXT++}
delete                {--TEXT--}
substitution          {~~OLD~>NEW~~}
note                  {>>NOTE<<}
line                  SYNTAX-HEAD ROLE-PREFIX? LABEL-PART TEXT [" " MOVE-NOTE]
ROLE-PREFIX           "[" ENCODED-ROLE "] "                                       (see Role prefixes)
LABEL-PART            LABEL " "  |  "{~~" OLD "~>" NEW "~~} "  |  "{--" OLD " --}"  |  "{++" NEW " ++}"  |  ""
                      (label text: see Labels as written; the substitution only when both sides have a label,
                      the delete or insert form when one side gained or lost its label)
MOVE-NOTE             "{>>moved from " [SRC_LABEL " "] SRC_ADDRESS "<<}"
origin line           "{>>" [SRC_LABEL " "] "moved to " [TEST_LABEL " "] TEST_ADDRESS "<<}"   (own line; no head, no role)
inserted block        SYNTAX-HEAD ROLE-PREFIX? "{++" [LABEL " "] TEXT "++}"
deleted block         SYNTAX-HEAD ROLE-PREFIX? "{--" [LABEL " "] TEXT "--}"
list-marker renumber  markdown variant, test block with label_source == "list_marker":
                      SYNTAX-HEAD ROLE-PREFIX? "{>>renumbered from " OLD "<<} " TEXT
                      (OLD = the source block's label text: label_raw, else list_marker, else label)
fence                 OPEN [INFO] "\n" BODY-WITH-MARKS "\n" CLOSE; OPEN = CLOSE = max(3, longest backtick run in the accepted body + 1) backticks
table                 header row, alignment row (markdown variant only), data rows, joined by "\n"; marks per cell
header notes          own lines before the first block, only when true, in this order:
                      "{>>filtered: " FIELD "=" V{","V} {"; " FIELD "=" V{","V}} "<<}"   (non-empty ChangeFilter fields, declared order)
                      "{>>alignment stopped early: the comparison budget ran out<<}"
                      "{>>" ("source"|"test") " dropped " COUNT " " KIND ": " REASON "<<}"  (each Dropped, source first)
document              lines joined by "\n\n", no trailing newline
```

The fence length is measured over the accepted body, the test text with its inserts, and not over deleted or old text, so that accept-all reproduces the test rendering exactly. A deleted run of backticks longer than the fence can therefore close the fence early in a markdown viewer; the annotated text is still parsed correctly by the reference reader, and the case does not occur in the 60 committed runs.

- An inserted or deleted subtree writes every text-bearing block on its own line, wrapped separately, with the syntax head and role prefix outside the mark.
- An address contains no spaces, so it is always the last token of a note. On the origin line, the words "moved to" split the two labels, which may themselves contain spaces: `{>>Schedule 2 moved to Schedule 3 /…<<}`.
- A list-marker label is renumbered with a note, not a substitution, because a substitution inside the marker would break the list.

### Escaping

CriticMarkup defines no escape, so this is a redlines convention: a backslash at delimiter sites, with a parity rule.

It applies to any document-derived text the renderer copies: block text, labels, op texts, cell texts, and the document-derived parts of notes, which are labels, addresses, filter values, `Dropped.kind` and `Dropped.reason`. It never applies to delimiters or syntax the renderer emits.

```
sites, each captured with its own backslash run:
  opener      (\\*)\{(?=\+\+|--|~~|==|>>)        the run before "{"
  closer      (?<=\+\+|--|~~|==|<<)(\\*)\}       the run between the operator and "}"
  separator   (?<=~)(\\*)>                       the run between "~" and ">"
  line start  ^(\\*)\[(?=[A-Za-z0-9_.%-]+\] )    only when roles=True, at the start of a line's content
                                                 (after SYNTAX-HEAD and any ROLE-PREFIX), and only where the
                                                 content would otherwise parse as a role prefix
escape:   each site's run of n backslashes becomes 2n+1, then the site character
emitter:  before every delimiter it emits ({++ {-- {~~ {>> ~> ++} --} ~~} <<}), the run of n backslashes that
          ends the text emitted so far becomes 2n
reader:   (1) a delimiter is live when its site run is even (zero included); an odd run makes the site literal
          (2) the run that ends the text before a live delimiter is halved
          (3) critic_unescape turns each site's odd run 2n+1 into n backslashes plus the site character;
              the line-start site is unescaped after strip_roles
```

| Input | Escaped | Note |
|---|---|---|
| `x++}` | `x++\}` | closer |
| `x++\}` | `x++\\\}` | closer with a backslash run |
| `a~>` | `a~\>` | separator |
| `a~\>` | `a~\\\>` | separator with a backslash run |
| `{++` | `\{++` | opener |
| `\{++` | `\\\{++` | opener with a backslash run |
| `[x] task` | `\[x] task` | roles on |
| `\[x] task` | `\\\[x] task` | roles on |
| `[link](u) here` | unchanged | not role-shaped |
| `[Party A] shall` | unchanged | not role-shaped |
| `if (a) { b++ }` | unchanged | no site |

- **Order.** The line-start site applies to the raw start of a line's first content piece; the other three sites apply to everything else. Roles never need escaping, because they are percent-encoded (below).
- **Other tools.** A third-party CriticMarkup tool ignores the backslash: it opens a mark at `\{++` and mis-pairs `use \{++ here {++new++}`. The reference reader is `tests/helpers/criticmarkup.py`, and no third-party stripper is one.
- **The markdown variant.** For text with no backslash of its own, a CommonMark viewer shows the original characters, except inside code spans and fences. Text that already carries a markdown escape renders with an extra backslash.

Measured through the real emitter and parser:

- E1: 1,311,111 strings, every string to length 6 over 10 symbols plus 200,000 random ones: 0 round-trip failures, and no live site left after escaping.
- E2: 60,000 complete lines, with syntax heads, roles on and off, hostile roles, role-shaped starts and marks: 0 failures.
- E3: 5 of 5 composite documents with backslash runs before emitted delimiters round-trip.
- E4: the line-start site is injective: 39,062 (roles, line) keys, 0 collisions.

### Role prefixes

A role, from [ADR-0005](0005-minimal-core-open-semantic-layer.md)'s open vocabulary, is written `[ENCODED-ROLE] ` after the syntax head and before the label.

- **Encoding.** `ENCODED-ROLE` is the role with every character outside `A–Z a–z 0–9 _ . -` replaced by `%XX` for each UTF-8 byte, in uppercase hexadecimal. `sub_clause` stays as it is, `a]b` becomes `a%5Db`, and `r~s` becomes `r%7Es`. `urllib.parse.quote` is not enough, because it always keeps `~`. The encoding is injective, and an encoded role can contain no escape site, no `]`, no space and no newline. `strip_roles` reverses it with `unquote`.
- **When.** Only when `roles=True` and `block.role is not None`.
- **Where.**
  - after the syntax head and before the label;
  - outside any whole-block mark;
  - never on table, row, cell or fence blocks, nor on tombstones;
  - on a multi-line quote, `> ` precedes every physical line and the role only the first;
  - on list items: markdown `3. [schedule] text`, text `[schedule] 3. text`.
- **HTML** writes `<span class="redlines-role">ROLE</span>`, unencoded and HTML-escaped. The legacy styles and rich show no roles.

### Labels as written

The readers keep each label exactly as matched, in `attrs["label_raw"]`, and renderers write `label_raw + " "`.

- `LabelMatch` gains `raw: str = ""` as its last field. `label_candidates` sets `raw=match.group(0).strip()`, computed before one trailing full stop is stripped from `label`.
- `_label_attrs` in `readers/text.py`, which the markdown reader shares, writes `attrs["label_raw"]` whenever a label pattern produced the label.
- A block labelled by a markdown list marker (`label_source == "list_marker"`) gets no `label_raw`; its marker as written is already `attrs["list_marker"]`.
- **The label text** is `label_raw`, else `list_marker` (text variant only), else `label`.
  - In the markdown variant, a list item with both `list_marker` and `label_raw` writes the marker as its syntax head and `label_raw` as its label: `1. 1.1 Access and Use…`.
  - With `label_source == "list_marker"`, the label part is empty in the markdown variant.
- Whitespace inside a label is kept; the whitespace between label and text becomes one space.
- The six sample-pair expected files are regenerated with `tests/corpus/sample_pair/regenerate.py`, and removing every `label_raw` key restores them byte for byte.
- `comparison-v2.json` is unchanged, because `attrs` is unconstrained, and nothing downstream reads `attrs`.

`label_raw` holds no separator. The separator is not data in the block model, since `text` already excludes it, and re-emission is canonical anyway.

### What accept-all and reject-all mean

`tests/helpers/criticmarkup.py` is the reference reader. `accept_all` and `reject_all` are exactly these steps:

1. **Parse** with a strict tokenising scan, not a regular expression.
   - A live opener (`{++`, `{--`, `{~~`, `{>>`) has an even backslash run before it. An odd run makes the whole opener literal text, its `{` included.
   - A mark ends at the first live closer (`++}`, `--}`, `~~}`, `<<}`): one with an even run between the operator and the `}`. A substitution's old side ends at the first live `~>`.
   - The run that ends the text before a delimiter, and a mark body before its closer, is halved. Then `critic_unescape` is applied to every text piece and body.
2. **Resolve.** Accept keeps insert bodies and the new side of substitutions, and drops deletions; reject does the reverse.
3. **`strip_notes`.** Remove every note together with one adjacent space: the space after it if the next text starts with one, otherwise the space before it.
4. **Lines.** Split on `\n`.
5. **`strip_roles`.** After the syntax head (`#{1,6} `, `( {4})*marker `, `> `), remove `[ENCODED-ROLE] `, where `ENCODED-ROLE` matches `[A-Za-z0-9_.%-]+` and no backslash precedes the `[`.
6. **Line-start unescape.** At the content start, an odd run before a role-shaped `[` is halved.
7. **Residue**, applied to both sides of every comparison, in this order:
   - strip each line of outer whitespace;
   - drop a table row whose cells are all empty;
   - drop an alignment row with no table row directly above or below it, judged after those empty rows are dropped and before any blank line is, so that a row of another table never counts as next to it;
   - drop a line that is empty, or that holds only a syntax head (ATX hashes, a list marker, `>`);
   - drop a fence whose body is empty.

The *test rendering* and the *source rendering* are the same renderer over `compare(test, test)` and `compare(source, source)`, put through the same steps. Comparisons are *exact* (list equality), *multiset* (`Counter` equality) or *loose* (multiset, after also removing all whitespace and a leading syntax head or list marker from each line).

Measured on the 60 runs, with the walk above:

- accept-all equals the test rendering exactly, line for line, on 60 of 60;
- reject-all equals the source rendering as a multiset on 49 of 60 strictly, and on 59 of 60 loosely.

The 11 strict failures have two causes. Unchanged runs carry the test's whitespace at change boundaries (`course_lesson6`, `whitespace_after_equal`, `adr-moves-mixed`, `msa-markdown-table`, `msa-text-heavy`), and syntax heads come from the test block: shifted ordered-list numbers, or a paragraph that became a list item. The one loose failure is `csa-1.1-to-2.0`. Its test turned numbered paragraphs into an ordered list, so 25 old clause numbers live only in `{>>renumbered from …<<}` notes, and reject-all cannot restore a value that is only in a note.

Documentation may claim no more than this: "accept-all reproduces the test rendering exactly; reject-all reproduces the source text as a multiset of lines, up to whitespace and markdown syntax heads, except where an old list-marker label moved into a note."

### Goldens and checks

The six styles over the tree get goldens of their own, which houfu reviews once: against the sample pair's `CHANGES.md`, and against the inputs of the small renderer cases. Three checks keep the goldens from being their own oracle:

- houfu's review of the frozen goldens;
- a drift test against the facade on the README fox pair: `Redlines(a, b, markdown_style=s, …).output_markdown == compare(a, b).output_markdown(s, …)` for all six styles, and for `custom_css` with classes. For `none`, through the real text reader, the tree rendering, the facade and `readme_quickstart/golden/none.md` are byte-identical;
- an invariant of the `none` style on the 60 runs: accept-all equals the test rendering on 60 of 60, and reject-all equals the source rendering *in source order* on 59 of 60 (the exception is csa-1.1-to-2.0, where clause 2.1's label changed only by its full stop: equal labels produce no change node and so no mark, once the readers keep labels as written), ignoring whitespace and syntax heads (49 of 60 strictly). The source order holds because the legacy styles strike a moved block at its origin.

The sample pair's annotated view, both twins unless a row says otherwise, must pass this checklist, and houfu approves its golden `annotated.markdown.md` in a review. Rows 1 to 8 are the eight changes of PRD § 3a, in its order.

| # | Check | Expected |
|---|---|---|
| P1 | accept-all equals the test rendering, line for line | true |
| P2 | reject-all equals the source rendering as a multiset of lines, strictly | true, *with* the residue rule; without it the markdown twin fails, because its inserted row rejects to `\|  \|  \|  \|` |
| P3 | exactly 11 lines carry a mark or a note: the blocks of the 10 change nodes, plus one tombstone | 11 |
| P4 | clause 11.5 appears once, on one line, unmarked | after `strip_roles`, the line is exactly `11.5 A notice given under this Agreement must be in writing and sent to the address of the receiving party set out above, or to any other address that the party notifies to the other in writing.` |
| P5 | in Schedule 2, exactly one of the eight items carries marks | the other seven equal their line in `test.md` or `test.txt` after `strip_roles` |
| P6 | `compare(x, x)` has no marks, and the output is byte-identical across `PYTHONHASHSEED` values | |
| 1 | the 2.4 definition | one insertion and no other mark: `… marked as {++confidential, or that the receiving party ought reasonably to treat as ++}confidential.` |
| 2 | 7.5 moved to 9.6, with an edit | destination: `[clause] {~~7.5~>9.6~~} Each party shall return or destroy the other party's Confidential Information within ten Business Days of a written request. {>>moved from 7.5 /section[1]/section[7]/list_item[5]<<}`. Next line: `The obligations in this clause continue for {~~three~>five~~} years after the end of the Term.` The tombstone `{>>7.5 moved to 9.6 /section[1]/section[9]/list_item[6]<<}` appears exactly once, directly after 7.4. Order: 9.5, 9.6, its body, then the Liability heading. No unmarked 7.5 anywhere |
| 3 | inserted 3.3, and two renumbers | `[clause] {++3.3 The Supplier may engage …++}`, `[clause] {~~3.3~>3.4~~} The Supplier shall meet …`, `[clause] {~~3.4~>3.5~~} The Supplier may change …` |
| 4 | the cross-reference | `… contrary to clause {~~3.3.~>3.4.~~}` |
| 5 | deleted (c) | `[sub_clause] {--(c) The Client pays the undisputed part of the invoice on the due date.--}`, between (b) and 5.5 |
| 6 | the inserted row | markdown: `\| {++Training day++} \| {++Week 9++} \| {++Client++} \|`, between the `Test report` and `Go-live sign-off` rows. Text: `[schedule] {++The training day is due by Week 9 and is owned by the Client.++}` |
| 7 | the whitespace-only change | as P4 |
| 8 | the repetitive schedule | markdown: `3. [schedule] The Supplier shall acknowledge a priority 3 incident within {~~four~>two~~} hours and shall restore the Services within {~~two~>one~~} Business {~~Days.~>Day.~~}`. Text: the same after `[schedule] 3. ` |

**Fixtures.**

- The sample pair's rendered goldens go in `tests/corpus/sample_pair/expected/rendered/`.
- The small cases go in `tests/renderer_cases/{four_kinds,moved_neighbour,nested_move,trailing_insert,hostile}/`, and `.gitattributes` gains `tests/renderer_cases/** -text`. No directory is created directly under `tests/corpus/` (ADR-0036).
- Every new golden is generated with `similarity="difflib"`, the `GOLDEN_BACKEND` of `tests/corpus/sample_pair/regenerate.py`. A test asserts that difflib and rapidfuzz produce identical change trees on each renderer case, and is skipped without rapidfuzz.
- All goldens are read and written with `newline=""`.
- The rich golden is `(plain, spans)` as JSON, not `Text.markup`, which churns on rich upgrades.

### Names and signatures

Each output has one key, the method name minus `output_`, plus `json`:

| Key | Python | CLI (M4) |
|---|---|---|
| `json` | `to_json()` (v2) | `--format json`, always v2 |
| `markdown` | `output_markdown(style)` | `--format markdown`, with the existing `--markdown-style` |
| `rich` | `output_rich()` | `--format rich` |
| `html` | `output_html()` | `--format html` |
| `annotated` | `output_annotated(syntax=None)` | `--format annotated`; `redlines annotate A B --syntax text\|markdown\|html` |
| `summary` | `output_summary()` (M5) | `--format summary`; `redlines summary A B` |

- **The CLI.** `--format` is a new option on the existing `compare` command. That command is also the command-less default, so `redlines A B --format json` and `redlines compare A B --format json` are one option on one command. `--format json` always emits v2. The `json`, `text`, `markdown` and `stats` subcommands, and `compare` without `--format`, are untouched. What `compare` emits without `--format` stays M4's call under R28.
- **The input format.** The CLI's input-format hint is `--input-format`. Python's `compare(format=)` keeps its input meaning. MCP argument names follow the CLI's, through [ADR-0025](0025-cli-as-thin-skin.md)'s shared layer.
- **`syntax`.** No output parameter in Python is named `format`, hence `syntax`. Any value other than `None`, `"text"`, `"markdown"` or `"html"` raises `ValueError` naming them, and the check is case-sensitive. With `syntax="html", roles=False`, no role spans are emitted.

```python
def output_markdown(self, style: MarkdownStyle | str = MarkdownStyle.RED_GREEN, *,
                    ins_class: str | None = None, del_class: str | None = None) -> str: ...
def output_annotated(self, *, syntax: Literal["text", "markdown", "html"] | None = None,
                     roles: bool = True) -> str: ...
def output_html(self) -> str: ...
def output_rich(self) -> rich.text.Text: ...
# output_summary(self) -> str lands in M5 (ADR-0016)
```

- `style` accepts a `MarkdownStyle` member, its value, or `"custom_css"`. Anything else, `None` included, raises `ValueError`. 0.6's `Redlines` maps `None` to `none`, and the facade keeps that.
- `ins_class` and `del_class` are allowed only with `"custom_css"`, and raise `ValueError` with any other style. They default to `redline-inserted` and `redline-deleted`.
- `MarkdownStyle` gains no member. The pinned `tests/test_corpus.py` builds its style list by iterating the enum and opens `golden/<style>.md` for each, so a seventh member fails the unmodified suite.
- `syntax=None` means `"markdown"` when `config.test_format == "markdown"`, and `"text"` otherwise.

**Rich.** `output_rich()` is the in-place text variant with the `rich` set, built only with `Text.append`, so document text containing `[bold]` stays literal. Its header line is `T change(s): N inserted, N deleted, N modified, N moved, N renumbered`, with the counts and the pluralisation of ADR-0038's header, and its notices follow in yellow. Headings are bold and roles are off. On a terminal without colour, deleted and inserted runs look alike, as they do in 0.6, and the docstring points to `output_annotated(syntax="text")`. The renderer uses `Text` only, because the declared floor `rich>=13.3.5` is below the 15.0.0 the lock resolves.

### Where the code lives, and determinism

The renderers are a package of private modules. The `Comparison` methods are the API, and the 0.6 rendering loops stay in `redlines.py`, untouched.

```
redlines/renderers/__init__.py   docstring; from ._html import FRAGMENT_VERSION, STYLESHEET; __all__ = ("FRAGMENT_VERSION", "STYLESHEET")
redlines/renderers/_marks.py     MarkSet; LEGACY (six styles + custom_css), CRITIC, HTML, RICH
redlines/renderers/_escape.py    critic_escape, critic_unescape, escape_line_start, encode_role, html_text, html_attr
redlines/renderers/_view.py      BlockStatus, ViewNode, build_view
redlines/renderers/_inplace.py   Segment, inline_segments; the in-place traversal and line syntax
redlines/renderers/_html.py      change list, document view, STYLESHEET, FRAGMENT_VERSION = "1.0" (ADR-0038)
redlines/renderers/_rich.py      the rich renderer; the only renderer module importing rich
(redlines/renderers/_summary.py  M5, ADR-0016)
redlines/changes.py              Anchor, Anchors, _under_a_move (ADR-0033, amendment); none in __all__
```

- `comparison.py` imports the renderer functions at module top, so `import redlines` reaches every renderer under Pyodide. Renderer modules import `Comparison` only under `TYPE_CHECKING`.
- An AST test asserts that each renderer import's top-level name is in `sys.stdlib_module_names`, is `redlines`, or, in `_rich.py` only, is `rich`. A test runs `python -W error -c "import redlines, redlines.cli"`, and `.github/scripts/pyodide_check.mjs` gains a call to each new method.
- pdoc publishes every public module, so the internals carry a leading underscore.

Output is deterministic, as N1 requires:

- fixed orders: blocks in view order; ghosts that share an anchor in source order; header notes in the grammar's order; counts in `ChangeCounts` order; CSS as a constant;
- prohibited: iterating a `set` for output, timestamps, random or `id()`-based ids, locale formatting, and formatting an enum other than through `.value`;
- floats are written as `repr(round(x, 4))`, the digits the JSON uses.

With `roles=True` there is one more exception: where an edit at the very start of a block leaves only one side's text beginning like a role prefix, such as `[2020] SGCA 5`, the escape serves the accept side, so reject-all may read `[2020]` as a role and drop it, or keep a stray backslash before it. A strict expected-failure test pins the limit.

## Amendment, 2026-10-19: choices the implementation fixed

Building the renderers (#192 to #195) and reviewing them against this ADR fixed ten details that the text left open or worded loosely. Two other choices are already in the Decision and are not repeated: the label part's delete and insert forms, for a block that lost or gained its label (`LABEL-PART`), and the fence length measured over the accepted body.

- **A bullet has no label.** The text variant writes no `- ` for one. A numbered item's marker is its label in the text variant (`1. First`) and its syntax head in the markdown variant.
- **Filtered-note values.** A boolean is written `true` or `false`, and `false` is a constraint, so it is written. A zero or an empty field was never set and is left out: `{>>filtered: kinds=modify,insert; min_chars=1; has_inline=true<<}`.
- **A quote composes with a head.** `> ` comes first, then the head, then the role. A quoted list is one `> ` chunk per item with a blank line between, which CommonMark reads as separate blockquotes, and a quoted heading is written `> Quoted heading` without its `#`, because the readers give it the kind `paragraph`.
- **The line-start escape is decided per side and per physical line.** *Order* puts that site at the raw start of a line's first content piece. The renderer works from what a reader recovers, so a `[` exposed by a removed note, or starting a continuation line of a quote, is escaped too, and where one string cannot serve both sides the accept side wins, which is the limit named under *Where the code lives, and determinism*.
- **An empty role is no role.** A block whose `role` is the empty string writes no prefix, because `ENCODED-ROLE` has at least one character and `[] ` could not be read back.
- **A row that gained or lost a cell** is drawn as its test row inserted and its source row deleted, so neither side reads back a cell the other lacks. Adding a column therefore draws every row twice, the header included, with the alignment row between the first pair. Accept-all stays exact, and reject-all recovers every source row.
- **A moved block with no line of its own** gets its note as a chunk of its own. A fence ends in its closing fence, so `{>>moved from SRC_LABEL SRC_ADDRESS<<}` follows it; a section, which moves only under a custom `move_kinds`, gets the same chunk before its first block.
- **An empty chunk is left out.** An empty paragraph therefore vanishes from every rendering, accept-all included.
- **A filter can drop a tombstone.** A move out of a deleted block has its tombstone inside the block's ghost. When a filter removes the deletion the ghost is not drawn, and the tombstone goes with it, so the destination's `moved from` note is then the only trace of the move.
- **A renumbered list-marker label is unmarked in the markdown variant of the six legacy styles.** The marker is the syntax head, so the label part is empty, and `DEL("1. ")INS("2. ")` after the head would read back as `2. 2. Alpha` and break the `none` style's accept-all. The text variant marks it (`<del>1. </del><ins>2. </ins>Alpha`), and the note-bearing sets say `{>>renumbered from 1.<<}`.

## Alternatives considered

**Walking the source document,** as R21a and ADR-0011 worded it. Accept-all then reproduces the test text only up to block order, and a moved block appears at its origin. Rejected: the test document is the one a reader asks about, and the exact accept-all invariant is the check that needs no golden.

**A replacement written as a delete then an insert,** as ADR-0011's illustration has it. Rejected: two constructs for one `InlineKind`, where the substitution is CriticMarkup's own form and keeps the annotated text a lossless encoding.

**A move as a delete plus an insert in CriticMarkup.** Rejected: it says "deleted" of a block that moved. **A move as a highlight, `{==…==}`.** Rejected: a highlight cannot nest around the inline marks a moved block carries.

**A third mark per legacy style for moves, or plain-text notes such as `[moved from 7.5]` in the document.** Rejected: the first is six inventions with no precedent, which render unpredictably in Streamlit and BBCode; the second changes the text a 0.6 user pastes elsewhere.

**ADR-0011's `<moved from="…">` in the HTML variant.** Rejected: `moved` is not an HTML element, and the `data-*` attributes are what a shell filters on.

**A modified fenced code block wrapped whole in a mark.** Rejected: `{--```lang` puts the fence opener mid-line, CommonMark stops seeing a fence, and the code renders as prose.

**Escaping with a zero-width joiner, with HTML entities, or by refusing such documents.** Rejected: a joiner is invisible but changes text a model copies; entities leave a literal `&#123;` in the text variant; and refusing fails on ordinary code, such as `'~> 7.0'`.

**Roles as a note, `{>>role<<} `, or no roles.** Rejected: the first puts a note on every line, and the second fails R21a.

**`attrs["label_prefix"]`,** the label with its punctuation and the whitespace after it. It gives the exact separator. Rejected: it bakes presentation whitespace into `attrs`, which every substitution must then split out. **A heuristic full stop** needs no reader change. Rejected: it is wrong on `1 Background`.

**`--format text`, or one name per annotated variant.** Rejected: `text` is already a legacy subcommand and an input format, and three variant names would give one output three keys.

**A per-change list for rich.** Rejected: that is [ADR-0016](0016-summary-renderer-in-core.md)'s summary in colour, and it is built once, in M5.

**Moving the 0.6 rendering loops into the renderer package, or lifting 0.6's style table out of `redlines.py`.** Both edit 0.6 code for no change in behaviour, and the drift test gives the same guarantee.

## Consequences

Positive: one traversal serves every in-place output, so placement, subtree emission and labels cannot drift between renderers. Accept-all is exact on 60 of 60 runs, a check that needs no golden. The annotated text is a lossless encoding of the test document and its ops, and it says "moved" exactly when the change list does. Escapes and roles are reversible under an exact grammar, with 0 failures over 1,311,111 fuzzed strings. The legacy styles keep 0.6's two-mark vocabulary. Labels come back as they were written. ADR-0011's open escaping question is closed.

Negative: reject-all is weaker than accept-all. It is a multiset of lines, up to whitespace and markdown syntax heads, and it loses old labels that live only in notes: 26 lines in `csa-1.1-to-2.0`, 25 of them renumber notes and one a label that changed only by its full stop and so has no change node. The output is a normalised document, not the input bytes. The escape is ours: the backslash shows in the text variant, third-party CriticMarkup tools ignore it, and text that already carries a markdown escape shows an extra backslash. A `[role] ` prefix would read as a CommonMark shortcut reference link if a `[role]: url` definition existed; the readers drop such definitions, but a consumer who pastes annotated markdown beside one would see a link. Six sample-pair expected files gain a key per labelled block. And `Comparison.output_markdown` is not byte-identical to 0.6, so two methods named `output_markdown` give different bytes for the same inputs; both docstrings say so.

## Revisit when

If a consumer needs reject-all to restore source order and syntax exactly, that is a second traversal over the source document, added beside this one, not a change to it. If the CriticMarkup specification or a widely used tool adopts an escape, align with it; the annotated text is parsed by agents, so changing its escape is a new ADR. If the readers start keeping link reference definitions, the `[role] ` prefix stops being safe. If the 1.1 readers bring structure the line syntax cannot express, such as quote depth or merged cells, extend the line syntax before any renderer works around it.

## Related

ADR-0005, ADR-0009, ADR-0011, ADR-0016, ADR-0025, ADR-0032, ADR-0033, ADR-0036, ADR-0038.
