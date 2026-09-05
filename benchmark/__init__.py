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

**What lives here, and what does not yet.** This module and its immediate
neighbours -- :mod:`benchmark.labels` (the label file: dataclasses, schema
validation, digest computation, the totality check) and
:mod:`benchmark.reanchor` (repairing addresses after a reader change) -- are
the shared foundation the rest of the benchmark is built on. The generator
(``generate.py``, ``mutate.py``, ``prepare.py``), the metric and report
(``score.py``, ``report.py``, ``units.py``, ``baselines.py``), the
labelling tool (``label.py``) and the runner (``run.py``) are separate
pieces of work, tracked against issues #141-#144, and land as this directory
fills in. See ``benchmark/README.md`` for the corpus layout and how to run
what exists today, and ``docs/adr/0034-benchmark-labels-and-metric.md`` for
the full design and the alternatives it rejected.

**Dependency direction.** Everything here may depend on :mod:`redlines`
(``redlines.blocks``, ``redlines.pipeline``), never the reverse. Nothing in
:mod:`redlines` imports :mod:`benchmark`.
"""

from __future__ import annotations
