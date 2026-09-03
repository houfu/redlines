# The sample pair: what changed, and where

`source.md` and `test.md` are the PRD § 3a demo pair — a short commercial
services agreement between two fictional parties, Northwind Systems Limited
(the Supplier) and Harbour Foods Group Limited (the Client), and an amended
version of it. `source.txt` and `test.txt` are the plain-text twins: the same
agreement with the markdown syntax taken out, so the same document can be read
by both readers and the M1 exit criterion ("parses into the expected trees
under `contract` and `markdown`") means something.

The amended version carries **exactly eight changes, one of each thing the
engine is meant to detect** (ADR-0013). Nothing else differs. Each is listed
below with the addresses involved, in the ADR-0029 syntax the trees use: a
path is the kind and 1-based index of each block from the root, so
`/section[1]/section[7]/list_item[5]` is the fifth clause of the seventh
section of the body.

The addresses are the same in the plain-text tree and the markdown tree —
that is the point of the twins — with one documented exception, change 6,
where the plain text has no table to put a row in. `expected/` holds the four
trees; regenerate them with `uv run python tests/corpus/sample_pair/regenerate.py`.

The change tree for this pair is M2's golden, not this directory's. What is
frozen here is the two documents and the four trees they parse into.

## The eight changes

| # | Change | Where in `source` | Where in `test` |
|---|---|---|---|
| 1 | A definition whose text changed | `/section[1]/section[2]/list_item[4]` (2.4) | `/section[1]/section[2]/list_item[4]` (2.4) |
| 2 | A clause moved from section 7 to section 9, edited on the way | `/section[1]/section[7]/list_item[5]` (7.5) and its body `…/paragraph[1]` | `/section[1]/section[9]/list_item[6]` (9.6) and its body `…/paragraph[1]` |
| 3 | A renumbering caused by an inserted clause | `/section[1]/section[3]/list_item[3]` (3.3), `…/list_item[4]` (3.4) | inserted `/section[1]/section[3]/list_item[3]` (3.3); the two clauses become `…/list_item[4]` (3.4) and `…/list_item[5]` (3.5) |
| 4 | A cross-reference updated to follow the renumbering | `/section[1]/section[9]/list_item[2]` (9.2), `cross_reference` span value `"3.3"` | same address, span value `"3.4"` |
| 5 | A deleted sub-clause | `/section[1]/section[5]/list_item[4]/list_item[3]` ((c)) | gone; 5.4 keeps (a) and (b) |
| 6 | An inserted table row | markdown: `/section[3]/list_item[3]/table[1]` has five rows | markdown: six rows, the new one at `…/table[1]/row[5]` ("Training day") |
| 7 | A whitespace-only change that is no change | `/section[1]/section[11]/list_item[5]` (11.5), hard-wrapped after "the address" | same address, same text, wrapped after "sent to the" |
| 8 | An edit inside a repetitive schedule | `/section[4]/list_item[3]` (Schedule 2, item 3) | same address, "four hours"/"two Business Days" → "two hours"/"one Business Day" |

## The changes in detail

**1. A definition whose text changed.** Clause 2.4 defines "Confidential
Information". `test` widens it: information "that is marked as confidential"
becomes information "that is marked as confidential, or that the receiving
party ought reasonably to treat as confidential". The block keeps its role
`definition` and its `defined_term` span over "Confidential Information" in
both versions, so the change is a text edit inside a definition, not a new
definition.

**2. A clause moved from section 7 to section 9 with a small edit inside it.**
Clause 7.5 (return or destroy the other party's Confidential Information)
leaves Confidentiality and arrives in Term and Termination as clause 9.6. The
clause text itself is *identical* in both versions — only the label and the
address change — so alignment has to recognise it as a move. The edit rides in
the unlabelled body paragraph attached to it, which both readers make a child
of the clause: "continue for three years after the end of the Term" becomes
"continue for five years". So the move and the edit are separable: the moved
block matches exactly, its child does not.

**3. A renumbering caused by an inserted clause.** A new clause 3.3 (the
Supplier may engage a subcontractor) is inserted in section 3. The old 3.3
(Service Levels and monthly reporting) becomes 3.4 and the old 3.4 (changing
how the Services are supplied) becomes 3.5. Three blocks move down one
address; only one of them is new.

**4. A cross-reference updated to follow the renumbering.** Clause 9.2 cites
the Service Level reporting obligation. In `source` it reads "contrary to
clause 3.3"; in `test`, "contrary to clause 3.4". The `contract` and
`markdown` profiles both extract a `cross_reference` span there, and the
span's `value` carries the bare label — `"3.3"` in `source`, `"3.4"` in
`test` — which is what lets M2 report "cross-reference updated to follow
renumbering" rather than "text changed". It is the only cross-reference span
in the document whose value differs between the two versions.

**5. A deleted sub-clause.** Clause 5.4 (withholding a disputed part of an
invoice) has three lettered sub-clauses in `source`. In `test`, (c) — pay the
undisputed part on the due date — is gone. (a) and (b) keep their labels and
their addresses, so the deletion is one missing child, not a rewritten list.

**6. An inserted table row.** Schedule 1's deliverables table gains a row,
"Training day | Week 9 | Client", between "Test report" and "Go-live
sign-off". In markdown that is a new `row` block with three `cell` children at
`/section[3]/list_item[3]/table[1]/row[5]`, and the "Go-live sign-off" row
moves from `row[5]` to `row[6]`.

*The one place the twins diverge.* A pipe table is markdown syntax, and the
plain-text reader has no table support (ADR-0013 keeps the 1.0 slice small),
so writing the pipes into `source.txt` would only produce a header row scored
as a heading (short, title case, no terminal punctuation) opening a section,
and the alignment row and every data row below it as fallback paragraphs — a
wrong tree, frozen in a golden.
The plain-text twin therefore states the same four deliverables as ordinary
sentences under Schedule 1, item 3, and the inserted row is an inserted
paragraph at `/section[3]/list_item[3]/paragraph[5]`. That subtree is the only
part of the document where the two trees differ in shape;
`tests/test_sample_pair.py` compares the twins block by block with exactly
that region set aside, and names it in the assertion.

**7. A whitespace-only change that should be reported as nothing.** Clause
11.5 (notices) is hard-wrapped across three lines in both versions, at
different points. The readers re-join hard wraps (PRD § 6b), so both trees
carry the identical single-line text and the change disappears before
alignment ever sees it. This is the pair's proof that the engine compares
documents, not bytes.

**8. An edit inside a repetitive schedule.** Schedule 2 is eight service-level
clauses of nearly the same shape ("The Supplier shall acknowledge a priority N
incident within X and shall restore the Services within Y") — the shape the
flat 0.6 engine gets wrong, because difflib's popular-token heuristic loses
the edit among the repetitions (ADR-0010, and `tests/corpus/repetitive_schedule`
where the same pathology is pinned). Item 3 tightens: "within four hours" and
"within two Business Days" become "within two hours" and "within one Business
Day". Every other item is byte-identical.

## What the pair also shows, without being a change

- **Roles.** Section 2 is a `definitions` section and each of its eight
  clauses is a `definition`; everything under Schedule 1 and Schedule 2 —
  headings, clauses and bodies alike — is `schedule`. The Background heading
  is `recital` and the Signatures heading is `signature`, but only the
  headings: the `contract` profile matches those two on the heading alone, so
  the clauses underneath them carry no role, where the schedule rules use
  `ancestor_heading` and reach the whole subtree. That asymmetry is the
  profile's, not the pair's, and it is a question for the owner rather than
  something to paper over here. The operative clauses (3.1, 7.2 and the rest)
  carry no role at all: the built-in `contract` profile assigns no `clause`
  role, though ADR-0005's recommended vocabulary has one.
- **Spans.** `party` spans over "Supplier" and "Client" where the recital
  introduces them, a `date` span over "1 March 2026" and "1 April 2026", an
  `amount` span over "USD 12,000", `defined_term` spans across the definitions
  section, and `cross_reference` spans over the clause and Schedule citations.
- **Numbering that restarts inside a schedule.** The body runs to clause 11.6
  and Schedule 1 starts again at 1. — a PRD § 6b hard case, handled by the
  `schedule` numbering reset in the profile rather than by arithmetic.
- **A small fallback count.** Three blocks in every one of the four trees fall
  through to a plain paragraph: the parties recital and the two signature
  lines. They carry no label and sit under no labelled block, so `fallback` is
  the honest answer, and `tests/test_sample_pair.py` pins the number at three
  so a regression that starts guessing shows up.
