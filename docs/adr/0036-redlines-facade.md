# ADR-0036: The `Redlines` facade: 0.6's code over 0.6's opcodes, with a change tree derived from them

**Status:** Accepted
**Date:** 2026-10-18
**Deciders:** houfu

## Context

[ADR-0003](0003-compatibility-facade.md) keeps the 0.6 surface working, "reimplemented over the new core as a facade that builds a one-block-per-paragraph tree". It makes the unmodified 0.6 test suite a hard release criterion, and it says that a style which cannot be byte-identical "should get its own note rather than a blanket relaxation of the criterion". M0 generated the golden files that criterion is checked against: seven cases in six styles, 42 files. M3 builds the facade, and what was measured before writing it changes how.

**One block per paragraph cannot be byte-identical.** 0.6 runs one `difflib.SequenceMatcher` over the whole document, with a `¶` token between paragraphs. The repository already holds 54 realistic pairs: the two benchmark corpora, both twins of the sample pair and the two benchmark-label fixtures, read as plain text, which is all the 0.6 API sees. On them, 130 of the 735 non-equal 0.6 opcodes straddle a paragraph boundary, in 39 of the 54 pairs. Typically a clause number is matched into the neighbouring clause, or a shared phrase runs across a break. A paragraph pair cannot hold such an opcode. Built as ADR-0003 describes, the facade fails 32 of the 237 runnable tests in the v0.6.2 test tree, and 534 of 576 byte comparisons: the seven golden cases, 35 small constructed pairs, each isolating one 0.6 quirk, and the 54 realistic pairs, each in six styles. With every 0.6 quirk faked in (synthetic flat opcodes, a rule that mimics where difflib leaves a `¶`, a non-default alignment), it is still byte-identical on only 16 of the 54 realistic pairs. `test_repetitive_schedule_reproduces_autojunk_pathology` cannot pass at all, because thirty paragraphs of about 46 tokens never reach difflib's 200-token autojunk threshold. The M0 goldens contain no cross-paragraph opcode, which is why M0 did not see this.

**Byte identity comes only from 0.6's own opcodes.** Every 0.6 output is a view of one token-level opcode list: `opcodes`, `changes`, `stats()`, `output_json()`, `output_markdown` and `output_rich`. Rendering from the core's character-offset `InlineOp`s instead fails 546 of the 576 comparisons. On 75 of the 96 cases, 337 op-sides differ from 0.6's text for the same edit: a raw separator where 0.6 has `¶ `, a missing trailing space that 0.6 gives a paragraph's last token, whitespace moved across an edit. Replaying the recorded opcodes through 0.6's own code gives 0 mismatches of 576, passes 237 of 237 runnable tests in the pristine v0.6.2 test tree, gives identical token surfaces on all 96 cases, and works with a custom character-level processor. A renderer over a real block tree reproduces 18 of the 42 golden files. It fails on the token stream's own artefacts: the trailing space before each break, an empty `<ins></ins>`, a literal `¶ ` inside `<del>`. So the new renderers need goldens of their own ([ADR-0037](0037-annotate-the-test-document.md)).

**Two constraints sit outside the outputs.** `tests/test_changes_api.py:458-480` makes every `import` raise while `Redlines(source, test)` is built and `.stats()` is called. The only function-local imports in the core today are `import Levenshtein`, twice in `stats`, and `import json` in `output_json`. Any other import on that path fails a pinned test far from its cause. And "unmodified" needs a definition. 8 of the 13 pinned `.py` files already differ from `v0.6.2`: six by `black` only, two by additions made during M1 and M2. The pinned `test_corpus.py` collects any new directory under `tests/corpus/` as a golden case. The tag's own `tests` and `examples` trees, run against current code with all extras, give 237 passed and 1 skipped in about 5 seconds.

**Which 0.6 is meant.** 75% of installs are a 2023 pin of 0.4.2 from the course environment. 0.4.2 already prints differently from the 0.6.2 goldens on three of the seven cases (`course_lesson6`, `whitespace_after_equal`, `punctuation_merge`), because whitespace-stripped token comparison shipped in 0.5.2, and the cleanup pass and `autojunk=False` in 0.6.2.

## Decision

### The mechanism: 0.6's code, and a comparison derived on demand

The `Redlines` class keeps its 0.6 code. It gains one private method that derives a one-block `Comparison` from the opcodes the instance already holds, by replaying them through the core's own `build_change_tree`. In plain words:

> The 0.6 outputs are 0.6's own code over the processor's own opcodes. The change tree is built from that same opcode list by `build_change_tree`, on demand. The processor runs where 0.6 ran it, in the setters, not in the builder's leaf slot. "Runs through the core" is exercised whenever `_comparison()` is called, which in 1.0 means by tests only.

The rule, in `redlines/redlines.py`:

1. The class's 0.6 code is not edited: `__init__`, both setters, `compare()`, `_diff_ops`, every output and every error message. The deprecation section below adds docstring notes only.
2. `def _comparison(self) -> Comparison` is added. It is private, and a method, not a property.
   - It raises 0.6's `ValueError` through `self._diff_ops` when nothing has been compared.
   - Otherwise it returns the derived comparison, cached against the identity of `self._diff_operations`. A setter assigns a new list, which invalidates the cache.
3. Derivation:
   - (a) Each side is `BlockTree.build(Block(kind="document", children=(Block(kind="paragraph", text=<side text, unmodified>),)))`.
   - (b) The alignment is constructed, never computed: `Alignment(pairs=(AlignedPair("/", "/", "root", 1.0), AlignedPair("/paragraph[1]", "/paragraph[1]", "positional", 1.0)), inserted=(), deleted=(), config=DEFAULT_ALIGNMENT, backend="difflib", pass_counts={"root": 1, "positional": 1})`. The paragraph pair's confidence is `1.0`, not a ratio read off the opcodes. That is harmless while the object is private, and is recomputed if it is ever made public.
   - (c) `_ReplayProcessor(source, test, ops)` is a `RedlinesProcessor` whose `process(s, t)` returns `ops` after checking that `(s, t) == (source, test)`. It raises `AssertionError` otherwise.
   - (d) `changes = build_change_tree(alignment, source_tree, test_tree, processor=replay)`. When `source == test` the builder short-circuits and the replay is never called.
   - (e) `ComparisonConfig(source_format="blocks", test_format="blocks", profile="", alignment=DEFAULT_ALIGNMENT, similarity="difflib", processor=type(self.processor).__name__)`.
4. Imports:
   - `redlines/redlines.py` imports `Block`, `BlockTree`, `Alignment`, `AlignedPair`, `DEFAULT_ALIGNMENT`, `build_change_tree`, `Comparison` and `ComparisonConfig` at module top. `redlines/__init__.py` imports `comparison` before `redlines`, so there is no cycle.
   - Function-local imports stay the three that exist: two `import Levenshtein` in `stats` and one `import json` in `output_json`. There are none in `redlines/{changes,alignment,blocks,processor,similarity,comparison,statistics,filters}.py` or in `redlines/renderers/`. An AST test enforces this.
   - A non-pinned twin of the import-patching test makes `__import__` raise only when the importing module's `__name__` starts with `redlines`. It runs `Redlines(a, b)`, `.stats()`, `.changes`, `.opcodes`, `.output_markdown`, `.output_rich` and `._comparison()` over multi-paragraph, custom-processor, identical and empty inputs.
   - The twin has no nupunkt case. nupunkt's own `load()` does a call-time `from nupunkt.utils.compression import …`, so a blanket patch makes even the unmodified 0.6 class raise.
5. `redlines/processor.py` is not edited. The benchmark's 0.6 baseline stays `WholeDocumentProcessor.process`.
6. "Byte-identical" means identical to v0.6.2, whose bytes the M0 goldens are, and not to 0.4.2.

On 63 inputs, the derived comparison validates against `comparison-v2.json` ([ADR-0033](0033-change-tree-wire-format.md)) and round-trips through `to_dict` and `from_dict`. It holds either no node or one `modify` node whose `inline` equals `inline_ops_from_opcodes` over the same opcodes, and the replay is called at most once. The eager variant under *Alternatives considered* wires the same derivation into the setters. It passed 237 of 237 on the pristine tree, the whole in-repository suite, and 6,000 hostile random pairs under three processors with 0 output differences. The lazy rule leaves that code path exactly as 0.6 wrote it.

### What `Redlines` exposes: nothing new

`Redlines` gains no public name. `_comparison()` stays private, and the class docstring says two things:

- "For a structural comparison of the same inputs call `redlines.compare(self.source, self.test)`; it is a different, block-aligned diff."
- "`Comparison.output_markdown(...)` is a method, while `Redlines.output_markdown` stays a property."

Under ADR-0003 nothing public is removed before 2.0, so a name added now is frozen until then. And the derived object is true only of a degenerate tree: it would publish a whole document as one `paragraph`, a pair "found" by the `positional` pass, a `fallback_count` of 1 on each tree, and `InlineOp` texts that differ from `changes`' on 337 op-sides in 75 of 96 cases: the same edits, in a different frame. An honest pair would need a pass name for a pair that was given rather than found, which widens [ADR-0032](0032-alignment-passes.md)'s closed `matched_by` vocabulary. A public `Redlines.comparison` would also be a fourth meaning of "compare", after the method, the function and the CLI command.

Three tests hold the line:

- a surface test pins `{n for n in dir(Redlines) if not n.startswith("_")}` to the v0.6.2 set;
- `test_v062_names_still_exported` checks that every name the v0.6.2 `redlines/__init__.py` exported is still importable from `redlines`;
- a test asserts the `_comparison()` properties above.

### Deprecation: the mechanism and a schedule, with no warning in 1.0

1.0 removes nothing and emits no runtime deprecation warning. It ships the mechanism, a test tripwire and this schedule:

| Release | `changes`, `redlines`, `get_changes` |
|---|---|
| 1.0 | a docstring note; no warning |
| 1.1 | `RedlinesPendingDeprecationWarning` |
| 1.2 | `RedlinesDeprecationWarning` |
| 2.0 at the earliest | removal |

These three are the only 0.6 names with a structural successor, `redlines.compare(...).changes`, and it is not a drop-in replacement: it is block-addressed with character offsets, where they carry token positions. Every other 0.6 name is on the README, course or CLI path, which never warns, or has no successor (`opcodes`, `OutputType`), or is reused by the new core, as the processors, `Document` and `PlainTextFile` are. The agent guide teaches the three names until M4 rewrites it, and the unmodified 0.6 suite calls them 49 times.

```python
class RedlinesPendingDeprecationWarning(PendingDeprecationWarning): ...
class RedlinesDeprecationWarning(DeprecationWarning): ...
def warn_deprecated(old: str, new: str, *, since: str,
                    category: type[RedlinesPendingDeprecationWarning] | type[RedlinesDeprecationWarning],
                    stacklevel: int = 3) -> None: ...
```

- These live in `redlines/_deprecation.py`, and both classes are exported from `redlines`.
- Nothing calls `warn_deprecated` in 1.0. 1.1 passes the pending category; 1.2 passes the deprecation category.
- `pyproject.toml` gains `filterwarnings = ["error::redlines.RedlinesPendingDeprecationWarning", "error::redlines.RedlinesDeprecationWarning"]`. Never `error::DeprecationWarning`: click 8.5 emits one.
- `tests/test_quick_path_is_silent.py` records warnings, with `simplefilter("always")`, over the README, the course example, `examples/` and every CLI command. It fails on any recorded warning whose `filename` is under `redlines/`, or whose category is either of ours. The second clause catches a warning attributed to the user's code by `stacklevel=3`.
- The docstrings of `changes`, `redlines` and `get_changes` gain: "Superseded by `Comparison.changes`, from `redlines.compare(...)` (block-addressed, character offsets; not a drop-in replacement). Not deprecated in 1.0; not removed before 2.0." The successor is spelt that way because pdoc reads a dot after a call as a reference to a sibling module.
- Before the first warning in 1.1, the public names wrap a private `_changes()`, so that `stats()` and `output_json()`, which reach `changes` internally, stay silent.

### What "unmodified" and "byte-identical" are checked against

- **Pinned by hash.** `tests/test_v062_contract_frozen.py` pins the SHA-256 of the 12 pinned test modules at the M3 base, `e3b8e01795553ba47c80b2accba7835a3a1cd45e` (main when M3 started); of the seven golden cases' `source.txt`, `test.txt` and `processor.txt`; of the 42 goldens; of `tests/documents/*`; and of `tests/corpus/regenerate_goldens.py`. `tests/test_corpus.py` already compares `Redlines(...).output_markdown` with all 42 goldens byte for byte, and a new `tests/test_readme_strings.py` runs the README's own examples.
- **The pristine tree in CI.** A `compat-v062` job on Python 3.12, which nupunkt needs, runs `uv sync --all-extras --dev` on a checkout with tags. It extracts `git archive v0.6.2 tests examples` into `$RUNNER_TEMP/v062` and runs `uv run pytest "$RUNNER_TEMP/v062/tests" -p no:cacheprovider`, deliberately without the repository's pytest configuration. It blocks merges once houfu makes it a required check, which is a repository setting.
- **Untouched in M3, docstrings included:** the 12 pinned modules, `tests/documents/`, the seven golden cases under `tests/corpus/`, and `tests/corpus/regenerate_goldens.py`. Their stale sentences stay as they are: `tests/test_corpus.py` and `tests/corpus/regenerate_goldens.py` say the goldens are "reused by M4", and `test_corpus.py` advises regenerating them when an output changes. Following that advice would now regenerate the oracle from the code under test, and it would fail the hash pins. `tests/corpus/regenerate_goldens.py` is never run after M3.
- **No new directory directly under `tests/corpus/`.** New renderer fixtures go under `tests/renderer_cases/` and `tests/corpus/sample_pair/expected/rendered/`.

## Alternatives considered

**The same derivation, run eagerly in the setters.** The setters call the processor inside `build_change_tree` through a recorder, so every construction builds the change tree. Measured: 0 mismatches of 576, 237 of 237 pinned, and the whole in-repository suite and 6,000 hostile pairs identical. Rejected: it costs 4 to 9% on every construction (5.39 against 5.07 ms on the repetitive schedule, 55.8 against 53.5 ms on `csa-1.1-to-2.0`) for an object nothing public reads in 1.0. And a malformed custom processor would then raise at construction, a failure 0.6 never had.

**The flat diff, projected onto a paragraph tree.** Byte-identical, because the outputs are still 0.6's own. Rejected: the projection is a third correspondence, which agrees with `align()` on only 15 of the 54 realistic pairs. 168 of the 735 realistic edits fall in merge or split components, which the 1.0 change kinds cannot express. It also costs 18% per construction.

**Recovering the opcodes from a one-block `compare()`.** Re-tokenise both texts and map every `InlineOp` offset back to a token index. Byte-identical with the built-in tokenisers. Rejected: a custom character-level processor, which R17 allows, makes the recovery raise `OffsetError`. Running `align()` over a single whole-document pair also costs 2.1 times the flat diff.

**One block per paragraph, as ADR-0003 wrote it, with a note per failing case.** Rejected on the measurements above. The note list would be `test_repetitive_schedule_reproduces_autojunk_pathology` (impossible), `test_paragraph_boundary_never_merged` (passes only under a non-default alignment) and 38 of the 54 realistic pairs. That is the blanket relaxation ADR-0003's revisit clause rules out. Under the mechanism chosen here, the note list is empty.

**`Redlines.comparison` returning the derived comparison.** It is the object the outputs came from. Rejected for the degenerate facts listed above, and for the pass name it would need.

**`Redlines.comparison` running a lazy paragraph-level `compare()`.** Real structure. Rejected: it contradicts the same instance's token view on 39 of the 54 realistic pairs, so one object would carry two models that disagree.

**`PendingDeprecationWarning` on the three names in 1.0.** Meets R46's former wording literally. Rejected: it produces about 49 warning events in the unmodified suite, and a warning whose replacement is not drop-in trains users to silence warnings. **`DeprecationWarning` in 1.0** has the same cost and is shown in notebook cells, which is where the course audience runs redlines.

## Consequences

Positive: the 0.6 surface keeps working by construction, not through a renderer that imitates it. The evidence is a pinned hash, the pinned suite and the pristine tag tree, and none of it can be regenerated from the code under test. Nothing is added to the construction path. No public name is frozen, so `Redlines.comparison` can still arrive later as a minor change. Course and notebook users see no warning in 1.0.

Negative: "reimplemented over the new core" means less than ADR-0003 hoped. The legacy renderers are not reimplemented over a tree, and the measurements say they cannot be. The core builds the change tree from the same opcodes, on demand, and in 1.0 only tests ask it to. 0.6's quirks are permanent until 2.0: the literal `¶ ` inside `<del>`, the empty `<ins></ins>`, the trailing space before a break. The facade's docstring names them. The facade keeps paying for `autojunk=False` on a whole-document diff: 7.7 times the autojunk-on time on the repetitive schedule, and 54 ms for a 5,000-token contract ([ADR-0010](0010-keep-difflib-for-leaf-diffs.md), note of 18 October 2026). A user jumping from 0.4.2 to 1.0 sees the output changes of 0.5.2 and 0.6.2 on three of the seven golden cases, and the 1.0 release notes owe them a paragraph. R46 is met as a mechanism and a schedule, which changes its wording. And stale sentences stay in the pinned files on purpose.

M4 inherits one obligation. `tests/test_examples.py::test_every_example_is_exercised` pins the set of files in `examples/`, so M4's task pages built from `examples/` need an additive edit to that pinned module, and a new hash pin.

## Revisit when

At 2.0, when the three superseded names may go and the facade's quirks can go with the 0.6 code. If a user needs the derived comparison in public, add `Redlines.comparison` as a minor change, with its confidence read off the opcodes and a pass name for a given pair. That reopens ADR-0032's closed vocabulary rather than borrowing `positional`. If the 1.1 pending warnings draw complaints from course users before the M4 guide has taught the successor, hold the 1.2 step. If a function-local import on the core path ever fails the pinned import test, the fix is to move the import to module top, never to edit the pinned test.

## Related

ADR-0003, ADR-0010, ADR-0032, ADR-0033, ADR-0037.
