# The alignment benchmark

What backs [ADR-0021](../docs/adr/0021-alignment-benchmark.md)'s decision to build an alignment
benchmark *before* tuning alignment, and [ADR-0034](../docs/adr/0034-benchmark-labels-and-metric.md)'s
design for the label file, the metric and the two corpora. This directory is not packaged into the
`redlines` wheel — see `benchmark/__init__.py` for why — so it is free to use dev-only tools and grows
independently of the 1.0 release surface.

## Layout

```
benchmark/
  labels.py            # the label file: dataclasses, schema validation, digests, totality
  labels/schema.json   # the published JSON Schema (draft-07) for a pair's labels.yaml
  reanchor.py           # repair label addresses after a reader change, by digest
  mutate.py             # the mutation operators, and the ground truth about what they did
  generate.py           # plan in, corpus out; derives the seeds, writes the labels
  plans/synthetic.yaml  # the committed plan: source documents, named plans, and the pairs
  fetch_neurotic.py     # dev-only: fetch neurotic_docx_bench text into external/
  prepare.py             # dev-only: fetch and normalise the ten hand-labelled pairs (#142)
  label.py               # init/check/sign one pair's labels.yaml (#142)
  corpus/
    synthetic/<pair>/{source.*, test.*, labels.yaml}           # committed (#141)
    hand/<pair>/{source.*, test.*, labels.yaml, NOTICE.md,
                 prepare_manifest.json, worksheet.md,
                 move_worksheet.md}                            # committed (#142)
    external/                                                  # gitignored — never committed
  results/latest.json  # committed; the metric's output, so a number changing is a diff (#143)
  REPORT.md             # committed; generated from results/latest.json (#143)
```

Pieces not yet written — the metric and report (`score.py`, `baselines.py`, `units.py`,
`report.py`) and the runner (`run.py`) — land against
[#143](https://github.com/houfu/redlines/issues/143) as a separate piece of work. This README
is updated as each lands.

## The hand-labelled tier (#142)

`benchmark/corpus/hand/` holds ten real before/after pairs: eight Common Paper standard
agreement tag pairs (CC BY 4.0) and two U.S. bill version pairs from govinfo.gov (public
domain, 17 U.S.C. § 105) — real edits nobody on this project made, which is the point
(ADR-0021's anti-self-marking mitigation, ADR-0034 D-9).

```
uv run python -m benchmark.prepare                                  # fetch + normalise all ten
uv run python -m benchmark.prepare --pair csa-1.1-to-2.0             # just one, for a retry
uv run python -m benchmark.label init benchmark/corpus/hand/<pair>   # draft labels.yaml + worksheets
uv run python -m benchmark.label check benchmark/corpus/hand/<pair>  # schema, digests, totality
uv run python -m benchmark.label sign benchmark/corpus/hand/<pair> --as NAME --role labeller
```

Every pair committed in this repository today is at the `init` stage: `labels.yaml` carries
`status: proposed` on every row, `review:` is absent, and **no row anywhere has `kind:
move`** — moves are never engine-seeded (`benchmark/label.py`'s own docstring says why), so a
pair's `move_worksheet.md` is where a human labels them, from a blank sheet. These are drafts,
not ground truth, until a maintainer has worked through each `worksheet.md`, corrected what the
engine got wrong, labelled moves independently, and run `label.py sign`.

## The synthetic tier (#141)

`benchmark/plans/synthetic.yaml` names ten source documents, seven named mutation plans and the
forty pairs built from them. Every pair's mutations come from a `random.Random` seeded with a
value **derived**, not counted, from the generator version, the document id and the plan id, so
adding a document or a plan to the plan file leaves every other pair — and every number already
published from it — untouched.

```
uv run python -m benchmark.generate --check    # is the committed corpus what the generator writes?
uv run python -m benchmark.generate            # rewrite it after changing the plan or an operator
```

The corpus is **committed, and regenerating it is a test**: `tests/test_benchmark_corpus.py`
rebuilds every pair into a temporary directory and compares byte for byte, so a change to an
operator that would move every published number is a diff a reviewer reads rather than a silent
drift. That test also loads every `labels.yaml`, re-derives every digest against the committed
documents, and asserts the totality rule.

The source documents are the repository's own corpus files and one ADR. That is deliberate:
ADR-0034 keeps the repository's documents *out* of the hand-labelled tier — labelling one's own
edits is the softest possible test — and puts them here instead, where what is being scored is the
mutation rather than the edit history.

## Two tiers, and the distinction is committed versus not

- **`benchmark/corpus/synthetic/`** and **`benchmark/corpus/hand/`** are committed: documents *and*
  labels. This is what CI runs and what a stranger can reproduce with nothing but a checkout.
- **`benchmark/corpus/external/`** is gitignored. It holds material such as
  [`neurotic_docx_bench`](https://github.com/frankiedrake/neurotic_docx_bench)'s extracted text — a
  useful mutation *source*, fetched by a dev-only script, never redistributed (its licence is AGPL;
  see `docs/adr/0034-benchmark-labels-and-metric.md` for what that does and does not let this project
  claim). Numbers computed against this tier, once the scorer exists, are reported as *not reproducible
  from this repository*.

## How to run

Nothing here is runnable end-to-end yet — that lands with `benchmark/run.py` (#143). The generator
and the hand-set tooling above both run today; everything else is loaded like any other module,
with the repository root on the path (already true under `uv run pytest`, via
`[tool.pytest.ini_options] pythonpath = ["."]`):

```python
from benchmark.labels import load_labels, verify_digests, check_totality

labels = load_labels("benchmark/corpus/hand/csa-1.1-to-2.0/labels.yaml")
```

Once the generator and scorer land, the intended entry point is
`uv run python -m benchmark.run --tier all`.

## Licence note

`benchmark/corpus/hand/` carries real, licensed legal text from external sources — Common Paper's
standard agreements (CC BY 4.0) and, for shape diversity, U.S. bill version pairs from govinfo.gov
(public domain, 17 U.S.C. § 105). Each hand-labelled pair directory carries its own `NOTICE.md` stating
its origin, licence and required attribution, and the top-level [README](../README.md#license) carries
the same licence line. `redlines` itself remains MIT-licensed throughout; committing these
documents does not change that, but their own licence terms travel with them and must be honoured by
anyone who redistributes the corpus.

## `benchmark/corpus/external/` and neurotic_docx_bench

`benchmark/fetch_neurotic.py` clones
[`neurotic_docx_bench`](https://github.com/frankiedrake/neurotic_docx_bench) and extracts its
documents' paragraph text, as a *mutation source* for local runs. It is dev-only and nothing in
CI or in any gate depends on it:

```
uv run --with python-docx python benchmark/fetch_neurotic.py
```

python-docx is deliberately not a dependency of this project in any form. Everything the script
writes goes under `benchmark/corpus/external/`, which is gitignored, and the script refuses any
other destination: the upstream repository is AGPL-licensed, so neither its documents nor the text
extracted from them is ever committed or redistributed. Extraction fails on some documents (#96
found 18 of the 763 unreadable); those are logged and skipped.

It does **not** re-run the bench's own adapter for a like-for-like comparison with the published
45.9 figure — that benchmark scores a tracked-changes DOCX, ADR-0014 rules out writing OOXML, and
that figure came from a third-party adapter rather than from this project.
