"""Run a producer script under several ``PYTHONHASHSEED`` values (#135).

Determinism is promised *per configuration* (ADR-0032, N1): the same two
trees under the same `AlignmentConfig` must serialise to the same bytes every
time, on every machine, whatever the interpreter's string-hash seed happens
to be that run. ``str.__hash__`` is seeded per process, so the only way to
catch a stray ``set`` iteration -- the shape that goes wrong quietly, because
it is consistent *within* one process and only ever differs *between*
processes -- is to actually run the code in separate processes and diff their
output byte for byte. A single process, however many times it calls the code
under test, can never see this failure mode at all.

This module is deliberately independent of what is being serialised.
`assert_byte_identical_across_hash_seeds` runs any self-contained script that
prints JSON to stdout; today that script builds an `Alignment` and prints
`Alignment.to_dict()` (``tests/test_determinism.py``), and the same function
is the hook #137's JSON v2 test reuses once it exists, printing
``Comparison.to_dict()`` instead. Nothing here mentions `redlines.alignment`
or `redlines.comparison` by name, on purpose.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Final

DEFAULT_HASH_SEEDS: Final[tuple[str, ...]] = ("0", "1", "42", "12345", "random")
"""Five seeds: three fixed small integers, one large one, and ``"random"``.

``"random"`` asks the interpreter to pick a seed itself (the default a bare
``python`` invocation gets); the fixed values pin specific, reproducible
seeds a failure can be replayed under. Between them they are not proof of
determinism for every seed there is -- no finite set of seeds is -- but a
`dict`-ordering bug that survives all five is not the bug this module exists
to catch.
"""


def run_script_under_hash_seed(script: str, *, seed: str, cwd: Path) -> str:
    """Run ``script`` as ``python -c`` under one hash seed and return its stdout.

    :param script: a self-contained Python script, passed to the interpreter
        with ``-c``. It must print its result to stdout and nothing else --
        any diagnostic output belongs on stderr, since stdout is compared
        byte for byte.
    :param seed: the value to set ``PYTHONHASHSEED`` to for this run.
    :param cwd: the working directory the subprocess runs in, so relative
        imports (``pythonpath = ["."]``, ADR-0034) resolve the same way they
        do under pytest.
    :return: the subprocess's stdout, unstripped.
    :raises subprocess.CalledProcessError: if the script exits non-zero.
    """
    completed = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "PYTHONHASHSEED": seed},
        capture_output=True,
        text=True,
        check=True,
        cwd=str(cwd),
    )
    return completed.stdout


def assert_byte_identical_across_hash_seeds(
    script: str,
    *,
    seeds: tuple[str, ...] = DEFAULT_HASH_SEEDS,
    cwd: Path,
) -> str:
    """Run ``script`` under every seed in ``seeds`` and require identical stdout.

    :param script: see `run_script_under_hash_seed`.
    :param seeds: the hash seeds to try; `DEFAULT_HASH_SEEDS` if left out.
    :param cwd: the working directory each subprocess runs in.
    :return: the shared stdout, so the caller can go on to assert things
        about its *content* (#135 also wants the configuration in force,
        including the resolved backend, to be visible in it) without running
        the script a sixth time.
    :raises AssertionError: naming the two seeds whose output first disagreed.
    """
    outputs: dict[str, str] = {}
    for seed in seeds:
        outputs[seed] = run_script_under_hash_seed(script, seed=seed, cwd=cwd)
    first_seed, first_output = next(iter(outputs.items()))
    for seed, output in outputs.items():
        assert output == first_output, (
            f"PYTHONHASHSEED={seed!r} produced different output than "
            f"PYTHONHASHSEED={first_seed!r}:\n--- {first_seed} ---\n"
            f"{first_output}\n--- {seed} ---\n{output}"
        )
    return first_output
