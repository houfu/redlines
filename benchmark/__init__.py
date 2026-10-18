"""The alignment benchmark: corpus, labels and (later) the metric (ADR-0021, ADR-0034).

**Not packaged.** This directory sits at the repository root, next to
``redlines/``, and is never built into the wheel -- ``pyproject.toml``'s
``[build-system]`` packages ``redlines`` only. That keeps the blocking
Pyodide job's plain-wheel import untouched, lets the code here use dev-only
libraries (``jsonschema``, and later ``python-docx`` for
``fetch_neurotic.py``) without adding a single runtime dependency, and makes
"publish the generator alongside the labels" -- ADR-0021's answer to the risk
that a benchmark we design could flatter us -- a directory anyone can read
rather than something buried in the test suite.

``[tool.pytest.ini_options] pythonpath = ["."]`` in ``pyproject.toml`` puts
the repository root on the path so ``import benchmark...`` works from a test
without this package needing an install step of its own.

**What lives here.** :mod:`benchmark.labels` (the label file: dataclasses,
schema validation, digest computation, the totality check) and
:mod:`benchmark.reanchor` (repairing addresses after a reader change) are the
shared foundation. On top of them sit the generator (``generate.py``,
``mutate.py``) and the hand-set tooling (``prepare.py``, ``label.py``), which
build the two committed corpora, and the metric: :mod:`benchmark.units` (flat
lines to block addresses), :mod:`benchmark.baselines` (the 0.6 floor),
:mod:`benchmark.score` (every published number), :mod:`benchmark.report` (the
markdown) and :mod:`benchmark.run` (the entry point that wires all of it
together and writes ``REPORT.md`` and ``results/latest.json``).

```
uv run python -m benchmark.run --tier all
```

See ``benchmark/README.md`` for the corpus layout, and
``docs/adr/0034-benchmark-labels-and-metric.md`` for the full design, every
metric definition and the alternatives each was chosen over.

**Dependency direction.** Everything here may depend on :mod:`redlines`
(``redlines.blocks``, ``redlines.pipeline``), never the reverse. Nothing in
:mod:`redlines` imports :mod:`benchmark`.
"""

from __future__ import annotations
