"""The 60 committed runs: every document pair the repository ships, as M3 sweeps them.

The M3 decision record measured its rules over one harness, and the tests that
hold those rules to their numbers have to run over the same one, or a figure
quoted from a sweep ("1 of 60 runs reorders") would be about some other set.
This is that enumeration, copied from the research scripts (``v2_sweep.py``,
``gaps_corpus_check.py``), in their order:

- the 8 directories under ``tests/corpus/`` that hold a ``source.txt`` and a
  ``test.txt``, read as text. The sample pair is one of them;
- the sample pair's two twins, ``source.md``/``test.md`` as markdown and
  ``source.txt``/``test.txt`` as text. The text twin is therefore in the list
  twice, as it is in theirs: 60 runs, 59 distinct pairs;
- every pair under ``benchmark/corpus/synthetic/`` and
  ``benchmark/corpus/hand/``, as markdown where the pair is ``.md`` and as text
  where it is ``.txt``: 40 and 10.

Every run is read with the format's default profile and nothing else set, the
way the sweeps called `redlines.comparison.compare`. A golden case's own
``processor.txt`` is not consulted.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent.parent

COMMITTED_RUN_COUNT: Final[int] = 60
"""How many runs `committed_runs` yields, so a test notices a pair arriving."""


@dataclass(frozen=True)
class CommittedRun:
    """One document pair and the format it is read as.

    :param name: the name the research scripts print for it, which is also a
        pytest id: ``tests/corpus/<case>``, ``sample_pair.md``,
        ``sample_pair.txt`` or ``benchmark/<tier>/<pair>``.
    :param source: the source file.
    :param test: the test file.
    :param format: ``"text"`` or ``"markdown"``.
    """

    name: str
    source: Path
    test: Path
    format: str

    def texts(self) -> tuple[str, str]:
        """Read both sides as UTF-8."""
        return (
            self.source.read_text(encoding="utf-8"),
            self.test.read_text(encoding="utf-8"),
        )


def committed_runs() -> tuple[CommittedRun, ...]:
    """Every committed run, in the research scripts' order (module docstring)."""
    runs: list[CommittedRun] = []
    for case in sorted((REPO_ROOT / "tests" / "corpus").iterdir()):
        source, test = case / "source.txt", case / "test.txt"
        if source.is_file() and test.is_file():
            runs.append(CommittedRun(f"tests/corpus/{case.name}", source, test, "text"))
    sample = REPO_ROOT / "tests" / "corpus" / "sample_pair"
    runs.append(
        CommittedRun(
            "sample_pair.md", sample / "source.md", sample / "test.md", "markdown"
        )
    )
    runs.append(
        CommittedRun(
            "sample_pair.txt", sample / "source.txt", sample / "test.txt", "text"
        )
    )
    for tier in ("synthetic", "hand"):
        for pair in sorted((REPO_ROOT / "benchmark" / "corpus" / tier).iterdir()):
            for extension, fmt in (("md", "markdown"), ("txt", "text")):
                source = pair / f"source.{extension}"
                test = pair / f"test.{extension}"
                if source.is_file() and test.is_file():
                    runs.append(
                        CommittedRun(f"benchmark/{tier}/{pair.name}", source, test, fmt)
                    )
    return tuple(runs)
