# ADR-0010: Keep difflib as the leaf differ

**Status:** Accepted
**Date:** 2026-08-26
**Deciders:** houfu

## Context

Once blocks are aligned (ADR-0008), the text inside each aligned pair still needs diffing. Today that is `difflib.SequenceMatcher` over regex word tokens, and it is the part of redlines that has worked well since 2023.

Two defects are real and measured. First, `SequenceMatcher` is constructed with the default `autojunk=True`, which for any sequence of 200+ items treats every token occurring more than 1% of the time as "popular" and refuses to start a match on it. On varied prose this is harmless — a 565-token contract with three scattered edits gives identical results with autojunk on and off. On repetitive text it is catastrophic and silent: a 1,050-token block of one clause repeated thirty times, with a single two-word change, is reported as `('replace', 11, 1050, 11, 1050)` — the whole document replaced. Repetitive blocks are common in real documents (schedules, price lists, "Intentionally omitted" runs).

Second, there is no semantic cleanup: "thirty (30) days" to "sixty (60) days" becomes two separate replaces split by an equal `(` token, so the JSON and the statistics both report two changes where a human sees one.

The alternative on offer is diff-match-patch, which every competitor uses. It is also archived upstream (Google archived the repository on 5 August 2024); the PyPI package tracks a community fork.

## Decision

Keep difflib. Disable `autojunk` (and expose it as an option). Add a cleanup pass that merges adjacent operations separated only by punctuation or whitespace. Keep the nupunkt sentence tokenisation as a leaf-level option, with paragraph structure always preserved — the current sentence mode reflows the document one sentence per paragraph, which is a defect of encoding structure in a `¶` token and disappears with the block model.

diff-match-patch stays out. The processor interface remains, so it can be added later as an alternative leaf differ without disturbing anything.

## Alternatives considered

**Replace difflib with diff-match-patch now.** Rejected: it adds a dependency (against ADR-0004) on an upstream-archived library, to fix problems that either have one-line fixes or disappear once diffs run inside short aligned blocks. The interesting algorithmic work in this project is block alignment, which diff-match-patch does not address at all.

## Consequences

Positive: no new dependency; the browser build stays trivial; the code path that most users already rely on is unchanged in character. Aligned blocks are short, so `autojunk=False` costs little in practice and the quadratic worst case is bounded by block size rather than document size.

Negative: our cleanup will be less sophisticated than diff-match-patch's `cleanupSemantic`, and word-boundary quality may lag competitors on pathological inputs. Turning autojunk off has a real cost on any remaining whole-document comparisons, which the 0.6 compatibility facade still performs — so the hygiene release should measure it.

## Revisit when

If leaf-diff quality shows up as a complaint after block alignment lands, add diff-match-patch as an optional processor rather than swapping the default.

## Related

ADR-0004, ADR-0008.
