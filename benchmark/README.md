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
  corpus/
    synthetic/<doc>/<plan>/{source.*, test.*, labels.yaml}   # committed (#141)
    hand/<pair>/{source.*, test.*, labels.yaml, NOTICE.md}   # committed (#142)
    external/                                                # gitignored — never committed
  results/latest.json  # committed; the metric's output, so a number changing is a diff (#143)
  REPORT.md             # committed; generated from results/latest.json (#143)
```

Pieces not yet written — the generator (`generate.py`, `mutate.py`, `prepare.py`, `units.py`), the
metric and report (`score.py`, `baselines.py`, `report.py`), the labelling tool (`label.py`), the
runner (`run.py`), and `fetch_neurotic.py` — land against issues
[#141](https://github.com/houfu/redlines/issues/141)-[#144](https://github.com/houfu/redlines/issues/144)
as separate pieces of work. This README is updated as each lands.

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

Nothing here is runnable end-to-end yet — that lands with `benchmark/run.py` (#143). What exists today
is loaded like any other module, with the repository root on the path (already true under
`uv run pytest`, via `[tool.pytest.ini_options] pythonpath = ["."]`):

```python
from benchmark.labels import load_labels, verify_digests, check_totality

labels = load_labels("benchmark/corpus/hand/csa-1.1-to-2.0/labels.yaml")
```

Once the generator and scorer land, the intended entry point is
`uv run python -m benchmark.run --tier all`.

## Licence note

`benchmark/corpus/hand/` will carry real, licensed legal text from external sources — Common Paper's
standard agreements (CC BY 4.0) and, for shape diversity, U.S. bill version pairs from govinfo.gov
(public domain, 17 U.S.C. § 105). Each hand-labelled pair directory carries its own `NOTICE.md` stating
its origin, licence and required attribution, and this README's own licence line is added alongside the
first hand-labelled pair (#142). `redlines` itself remains MIT-licensed throughout; committing these
documents does not change that, but their own licence terms travel with them and must be honoured by
anyone who redistributes the corpus.
