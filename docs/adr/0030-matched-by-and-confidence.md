# ADR-0030: Report how every block was recognised, with a reserved fallback and a bounded confidence

**Status:** Accepted
**Date:** 2026-09-03
**Deciders:** houfu

## Context

[ADR-0006](0006-structure-profiles.md) makes three reporting obligations mandatory rather than nice to have, on the grounds that "a wrong profile produces a confidently wrong tree": every block records how it was recognised (`matched_by`) and a confidence, and the tree reports how many blocks fell through to a plain paragraph. R1d and R3 restate them as requirements, and [ADR-0028](0028-profile-file-format.md) leans on them again — a bare-number label pattern will mis-label a paragraph opening "2019 saw…", and `matched_by` plus confidence is named there as what makes that visible rather than silent.

What none of those settle is what the fields *contain*. Three readers land in M1 and M2 (plain text, markdown, and whatever a third party writes), and if each invents its own vocabulary and its own idea of what 0.7 means, the fields become decoration: unusable in a filter, unusable in a summary, and actively misleading in a comparison between two readers' output.

## Decision

**`matched_by` is a short string naming the rule that recognised the block.** Its vocabulary is open, like `role` ([ADR-0005](0005-minimal-core-open-semantic-layer.md)), with a recommended `family:detail` shape:

| Value | Meaning |
|---|---|
| `label:<pattern name>` | a profile `label_patterns` entry matched; the detail is that entry's `name` |
| `heading:<signal>` | recognised as a heading; the detail is the signal that decided it (`all_caps`, `reset`, `atx`) |
| `markdown:<syntax>` | carried by markdown syntax; the detail is the syntax (`atx`, `fence`, `pipe_table`) |
| `continuation` | reserved — an unlabelled block attached to the labelled block above it |
| `fallback` | reserved — nothing matched |
| `document` | reserved — the tree's root, which no rule recognises because it *is* the tree |

Three values are reserved and exact; everything else is open, and a third-party reader is expected to use a family of its own (`examples/custom_reader.py` uses `clause-file:<TAG>`). The detail after the colon is deliberately the profile's own rule name, so "which rule did this?" is answerable by reading the profile the user wrote rather than by reading redlines' source.

**`fallback` is counted, and only `fallback`.** `BlockTree.fallback_count` is exactly the number of blocks whose `matched_by` is the string `fallback`. That is why the root has its own reserved value: a root reported as `fallback` would make every tree's count one too high, including a perfect parse. The block model applies that value rather than trusting readers to remember it — a block of kind `document` constructed without a `matched_by` takes `document`, not the field default — so a reader that forgets the keyword cannot silently inflate the one number the tree exists to report. The count is the headline number for "did this profile fit this document", and it stays comparable across readers because it counts an exact string rather than a family.

**`confidence` is a float in [0.0, 1.0], and out-of-range is an error, not a clamp.** It is *the reader's own certainty that its structural decision about this block is right* — nothing else. It is not a quality score for the text, not a probability in any calibrated sense, and not a measure of how well the profile fits overall (`fallback_count` is that). The bands the built-in readers use, and that a third-party reader should follow to stay comparable:

| Confidence | The reader is saying |
|---|---|
| 1.0 | the format states it: a markdown `##`, a fenced block, a declared record tag |
| 0.7–0.99 | a profile pattern matched unambiguously, at the start of the block, with no competing interpretation |
| 0.3–0.69 | inferred from a heuristic that can be wrong: a heading score, an alpha/roman label resolved from the style stack, a continuation attached by position |
| 0.0 | `fallback` — nothing matched, and the block is a paragraph because everything is a paragraph |

`0.0` and `fallback` therefore travel together, and the block model's defaults are exactly that pair: a block constructed without saying how it was recognised claims nothing. (The `document` kind is the one exception, above: it is the tree, so it defaults to `document` instead.)

**Neither field may influence alignment.** R2 already confines alignment to text, with role as a bounded tie-break; `matched_by` and confidence are output, and a reader that tuned its confidence to steer matching would make alignment failures unexplainable, which is what [ADR-0008](0008-multi-pass-block-alignment.md) exists to prevent. M2's alignment records its *own* `matched_by` on a change pair, naming the alignment pass; that is a different field on a different object and the collision of names is deliberate — both answer "how do you know?".

**`dropped` sits on the tree, not the block**, as a tuple of `Dropped(kind, count, reason)` (R3): a block that was dropped has nowhere to carry its own report. `kind` is the reader's own word for what was thrown away, `count` how many, `reason` one sentence a user can act on. A reader that drops nothing reports an empty tuple — a claim it is making, not a default it forgot.

## Alternatives considered

**A closed enum for `matched_by`.** Rejected for the same reason ADR-0005 keeps roles open: the values name rules that live in *user-written profiles*, so a closed set would either be meaninglessly coarse (`label`, `heading`, `none`) or need a release every time someone adds a pattern. Reserving three exact values gets the one guarantee that matters — a countable fallback — without closing the rest.

**A boolean `is_fallback` instead of confidence.** Genuinely tempting: it is what `fallback_count` needs, it is unambiguous, and it cannot be miscalibrated. Rejected because it collapses the middle of the range, and the middle is where the interesting failures are: an alpha/roman label resolved from the stack (PRD § 6b) is not a fallback and not a certainty, and a reviewer looking for likely mis-parses wants exactly those blocks. The boolean survives as the reserved `fallback` value; confidence adds the gradient.

**Structured provenance** — a record of the rule, the pattern, the matched span and the competing candidates. Rejected for 1.0 as ADR-0018's "deeply nested or clever": it would be a second data model to version alongside the change tree, and everything a consumer has asked for so far is answered by a string and a number. The `attrs` mapping is where a reader that wants to record more puts it, without putting it in the core schema.

**Calibrating confidence against the benchmark corpus** (M2, ADR-0021), so 0.8 means "right about 80% of the time". Rejected as a promise 1.0 cannot keep — there is no labelled structure corpus, only a labelled *alignment* one — and a number that claims calibration it does not have is worse than an honest ordinal. The bands above are ordinal and documented as such.

**Per-field confidence** (one for the label, one for the level, one for the role). Rejected: four numbers where users have asked for none yet, and the block is the unit everything else in the model addresses.

## Consequences

Positive: "how do you know?" is answerable per block, in the vocabulary of the profile the user wrote, and "did this profile fit?" is one integer on the tree. A reviewer can sort by confidence, an agent can refuse to act on a tree whose fallback count is most of it, and the site can show a `dropped` notice (R39) because the data is there. The trust boundary in ADR-0028 gets its reporting half: a bare-number pattern mis-labelling "2019 saw…" produces a `label:` block with a mid-band confidence rather than a silent lie.

Negative: an open vocabulary means two readers' `matched_by` values are not comparable beyond the three reserved ones, and confidence is a reader's self-assessment — the number a reader is *least* able to be objective about. Both are mitigated by documentation and by the exactness of `fallback`, and neither is load-bearing for anything but reporting, which is the reason it is safe to leave them soft. There is also a real risk that consumers threshold on confidence (`> 0.8`) as though it were calibrated; the docstrings say plainly that it is ordinal, and 1.0 ships no threshold of its own.

## Revisit when

If a consumer (our own summary renderer included) starts thresholding on confidence in a way that changes behaviour rather than presentation, the number needs calibrating against a labelled structure corpus, or replacing with the boolean plus an explicit "uncertain" flag. That is the signal, and it should arrive with the M2 benchmark rather than before it.

If the built-in profiles converge on the same handful of `matched_by` values in practice, promote that handful to a documented guaranteed set — the same escape hatch ADR-0005 reserves for roles — while leaving the vocabulary open.

## Related

ADR-0005, ADR-0006, ADR-0008, ADR-0021, ADR-0028, ADR-0029.
