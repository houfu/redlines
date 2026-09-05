# ADR-0031: Let a role rule look at the block itself: `text` and `label` match kinds, with a `kind` filter

**Status:** Proposed
**Date:** 2026-09-05
**Deciders:** houfu

## Context

ADR-0028 shipped `role_rules` with three match kinds — `heading`, `ancestor_heading`, `parent_role` — and named the gap in the same breath: all three are structural, keyed off a heading's text or a role already assigned, so no rule can look at the block it is deciding about. A fourth `text` kind was considered and deferred, with the revisit set at the semantic pass (#104): "where the semantic pass either wants it or demonstrates it does not." #104 has landed, and [#130](https://github.com/houfu/redlines/issues/130) is that revisit.

The evidence came in three pieces.

**The pass wanted it, and said so.** PRD § 6b's definitions heuristic — *quoted term, "means", text* — is a rule about a block's own text, and `redlines/semantic.py` had to write it in Python because the format could not say it. The module names that in its own docstring as "exactly the deferred `text` match kind" and "the evidence ADR-0028 asked #104 for." That is a hard-coded rule inside the one stage ADR-0006 says should take everything from the profile.

**The document we ship to demonstrate the semantic layer mostly has none.** Across the source side of the section 3a sample pair under the built-in `contract` profile, 72 of 102 blocks carry no role. Of the text-bearing blocks without one, 43 are labelled list items — every operative clause and sub-clause, 3.1, 7.2, 9.4 and the rest — and four are paragraphs. Three roles fire where a heading gives them away (`definitions`, `recital`, `schedule`, `signature`), and nothing fires on the body of the agreement. R1c has change nodes carry the role of the block they affect, ADR-0016's summary line is "address, role and inline detail," ADR-0019's site shows "a block-change list with roles," and ADR-0005's own revisit condition names `clause` as one of the three roles to promote to a guaranteed set. If the role is the headline, the built-ins have to be able to write it on the blocks a contract is made of.

**The deferred `text` kind would not have fixed that.** This is the finding that reframes the issue. A reader strips the label before the semantic pass runs, so clause 3.1's own text is "The Supplier shall supply the Services…" — there is nothing in it that says *clause*. What identifies a clause is its `label` and its `kind`: a `list_item` carrying a decimal label. A `text` match kind, on its own, closes the gap ADR-0028 named (`quote`, the definition shape, a "Note:" paragraph) and leaves the gap the sample pair shows wide open. The gap was never "no rule can see the text"; it is "no rule can see the block."

## Decision

Two new match kinds join the three, both about the block itself:

- **`text`** — the block's own `text` matches `pattern`. Searched, not anchored, like every other pattern in the format; the text is what the reader left after stripping the label, so `'^"[^"]+" means\b'` sees the definition and not its number.
- **`label`** — the block's own `label` matches `pattern`. A block with no label never matches, whatever the pattern. Labels are matched as the reader spells them — `1.1`, `(a)`, `(i)`, `A`, `IV`, `Article 5` — so `'^\d+(?:\.\d+)*$'` is a decimal clause and `'^\(?[A-Za-z]+\)?$'` a lettered or roman sub-clause.

And one optional field, **`kind`**, on any rule but `heading`: the rule applies only to blocks of that structural kind, one of the closed `BlockKind` values (ADR-0005). It is what lets a rule say "a `list_item` whose label is decimal" rather than "anything whose label is decimal," and it is rejected on `heading` rules because a heading rule already names its kind. The loader validates the value against `redlines.blocks.BLOCK_KINDS`, so a typo is an error with a field path, not a rule that silently never fires.

Both new kinds are **self-evidence**: in the pass's proximity model they claim a block at distance 0, the closest evidence there can be. They otherwise behave exactly as `heading` and `parent_role` do — tried in list order, first match wins, no proximity exception. The one interaction worth stating is with the definitions heuristic, the rule the pass writes in Python because no profile can. It used to compete on distance, claiming a member of a definitions section from the heading beside it, one step away; a `clause` rule at distance 0 would then have beaten it on any tree with no section block to carry a `parent_role` — the flat run of headings a third-party reader emits — and turned every definition under a Definitions heading into a clause. So the heuristic now takes the list position of the profile rule that names the role it is assigning (`definitions` for the section and its heading, `definition` for the members) and is settled against the profile's own claim by list order, like everything else. A profile that lists `clause` after `definition`, as both built-ins do, gets definitions on every tree shape; one that lists it before has said what it means; one that never names `definition` ranks the heuristic's member claim after its last rule. The block's `attrs["semantic"]` says which rule won either way.

What the pass records follows the existing shape: `role_match` is `text` or `label`; `matched` holds the substring a `text` pattern found and `label` the label a `label` pattern matched; `kind` is recorded where a filter was set.

**The built-in profiles.** `contract` and `markdown` both gain, listed last so that every existing rule keeps precedence over them:

- `clause` — `label`, `kind: list_item`, a decimal label;
- `sub_clause` — `label`, `kind: list_item`, a parenthesised or dotted letter or numeral.

They also gain `ancestor_heading` rules for `recital` and `signature`, mirroring the pair `schedule` already has. Those were an open asymmetry before — `tests/corpus/sample_pair/CHANGES.md` flagged that the two roles landed on the heading alone and left it "a question for the owner" — and adding `clause` forces the answer, because without them clause 1.1 of the Background section becomes a `clause` when it is a recital. `markdown` gains one `text` rule, `note` on a paragraph opening "Note:" or "Drafting note:", the drafting-format idiom its heading rule for `note` already targets. `text` is otherwise used by no built-in: the roles a contract's structure gives away are already given away by structure, and `text` is there for what structure cannot see — `quote`, `boilerplate`, a definition sitting outside its section — which a house profile names for its own precedent bank. The worked example `tests/profiles/example_contract.yaml` gains a `clause` rule so the R1f exercise shows the kind.

## Alternatives considered

**Leave it alone,** the issue's own case against. A label plus a kind already says "numbered clause," so `role=None` there is honest, and the vocabulary is easier to grow than to shrink. Rejected on the three pieces of evidence above: the pass already hard-codes one text rule the format is supposed to own; the consumers downstream read role as the primary signal, not label-plus-kind; and every role ADR-0005 expects to guarantee has to be one a built-in can assign. The point about honesty survives in a narrower form — a block the built-ins cannot place still gets `None`, never a guess — and is why the new rules are listed last and gated on `kind`.

**`text` alone,** as ADR-0028 framed it, with the two-try behaviour `heading` already has: the pattern against the block's text, then against the block as written with its label rejoined, so that `'^\d'` reaches the label through the line. Rejected because it makes a pattern's subject ambiguous — `'^\('` written for `(a)` also matches text that opens with a parenthesis — and leaves "match on the label only" inexpressible. Two plainly named kinds, one subject each, is what ADR-0028's "flat, plainly named" asks for.

**One `block` kind with several optional fields** — `text_pattern`, `label_pattern`, `kind`, `level`, all combinable. Rejected: that is a query language wearing a flat mapping, and ADR-0028 chose one rule, one pattern, one subject on purpose. `kind` is the single filter that earns its place, because kind is the one thing a pattern over text or label genuinely cannot see.

**Matching on `matched_by` or `level`** — "a block matched by `label:decimal`," "a block at level 3." Rejected. `matched_by` is reader provenance (ADR-0030), and a profile keying roles off it would couple to its own pattern names; `level` is derived from the label pattern's own depth mode and so says nothing a label regex cannot. Both would add an axis for no case the two kinds above fail to express.

**Readers assigning `quote` and `code` themselves,** from the syntax they see. Not decided here. ADR-0028 was right that a reader sees the fence and the profile does not; the pass already leaves a role a reader put there alone, so that door stays open, and `text` neither needs it closed nor closes it.

## Consequences

Positive: the built-in `contract` profile now writes a role on the body of a contract, not only on its furniture; every role in ADR-0005's candidate guaranteed set is one a built-in assigns; the match-kind vocabulary is symmetric — a rule can look at itself, its parent or its ancestors — and every rule is still one pattern over one named subject. The definitions heuristic is the only rule left that the format cannot express, and the reason is now a stated one: it is a majority vote over a section's members, which no per-block rule can be.

Negative: five match kinds and a filter field, where ADR-0028 had three and none, and the loader, schema, drift tests and semantic dispatch all grow with them. A role on every numbered block raises the cost of a wrong label — a paragraph opening "2019 saw…" that a bare-number pattern mislabels is now also a `clause` — which is exactly what `matched_by` and per-block confidence exist to make visible (ADR-0030), and a reason the rules are gated on `kind: list_item`. The four sample-pair goldens change, and any consumer that pinned role counts moves with them. The `recital` and `signature` widening is a profile-content change riding on a format change; it is here because the format change makes the old answer wrong, not because it was independently due.

## Revisit when

If the summary renderer (M3) or the MCP `summary` tool (M5) find that `clause` on every numbered block is noise — a summary where every line says "clause" carries no more than one that says none — drop the built-in rules, not the kinds. If a profile author needs depth that a label pattern cannot express ("`1.1.1` is a `sub_clause`, `1.1` is not" is expressible; "the third level, whatever its style" is not), that is the signal for a `level` field, and not before. If a reader starts assigning roles from syntax, decide then whether `quote` and `code` belong to the reader or the profile. And when M3's renderers begin relying on `definition`, `clause` and `schedule` being present, that is ADR-0005's own revisit condition: promote them to the documented guaranteed set.

## Related

ADR-0005, ADR-0006, ADR-0028, ADR-0030. Issues [#104](https://github.com/houfu/redlines/issues/104), [#130](https://github.com/houfu/redlines/issues/130), [#136](https://github.com/houfu/redlines/issues/136).
