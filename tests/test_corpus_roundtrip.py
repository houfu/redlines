"""Every committed run survives `statistics()`, `to_dict()` and `from_dict()` (D22, D4).

The M3 sweeps all start the same way: compare a committed pair, serialise it
with ``to_dict(include_alignment=True)``, rebuild it with
`redlines.comparison.Comparison.from_dict`, and read the result. M2 shipped with
``statistics()`` -- and so ``to_dict()``, which embeds it -- raising
``KeyError: '/section[6]/section[1]'`` on
``benchmark/corpus/hand/govinfo-hr4668-ih-to-rh``, and nothing ran the whole
corpus through either call, so nothing noticed (ADR-0033, amendment). This
module runs all 60 committed runs (``tests/helpers/committed_runs.py``)
through all of it.

Beyond "does not raise", four things are held on every run:

- the payload round-trips: what ``from_dict`` rebuilds serialises to the same
  JSON. Equality is on the payload, not on the objects, because confidence is
  rounded to four places on the wire and only there;
- the change list rebuilds from what the wire carries: `build_change_tree`
  over the rebuilt alignment and trees gives the serialised list back, order
  included. The renderers read a rebuilt comparison, so the order a delete
  sits in may depend only on fields that survive the trip (D15, rule 7);
- `redlines.changes.Anchors` places every source block the same way from the
  rebuilt comparison as from the original, and every anchor's ``after`` is a
  child of its ``test_parent``;
- two builds of the same run give identical payloads (N1): the change list,
  its order and the statistics are a function of the input and nothing else.

Each run is compared under the default backend, so a runner with rapidfuzz
installed and one without (CI's Python 3.10 job) each check their own.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

import pytest

from redlines.changes import Anchors, build_change_tree
from redlines.comparison import Comparison, compare

from tests.helpers.committed_runs import (
    COMMITTED_RUN_COUNT,
    CommittedRun,
    committed_runs,
)

RUNS: tuple[CommittedRun, ...] = committed_runs()
BY_NAME: dict[str, CommittedRun] = {run.name: run for run in RUNS}
NAMES: list[str] = [run.name for run in RUNS]


@lru_cache(maxsize=None)
def compared(name: str) -> Comparison:
    """One committed run, compared once per session."""
    run = BY_NAME[name]
    source, test = run.texts()
    return compare(source, test, format=run.format)


@lru_cache(maxsize=None)
def payload(name: str) -> str:
    """The run's ``to_json(include_alignment=True)``, written once."""
    return compared(name).to_json(include_alignment=True)


def rebuilt(name: str) -> tuple[dict[str, Any], Comparison]:
    """The run's payload re-parsed, and the comparison rebuilt from it."""
    data: dict[str, Any] = json.loads(payload(name))
    return data, Comparison.from_dict(data)


def test_the_harness_is_the_sixty_committed_runs() -> None:
    """The figures quoted from the M3 sweeps are about exactly these runs."""
    assert len(RUNS) == COMMITTED_RUN_COUNT
    assert len(BY_NAME) == COMMITTED_RUN_COUNT
    assert sum(run.name.startswith("benchmark/hand/") for run in RUNS) == 10
    assert sum(run.name.startswith("benchmark/synthetic/") for run in RUNS) == 40
    assert "benchmark/hand/govinfo-hr4668-ih-to-rh" in BY_NAME


@pytest.mark.parametrize("name", NAMES)
def test_statistics_and_to_dict_do_not_raise(name: str) -> None:
    """``statistics()`` is total over the corpus, and so is ``to_dict()``."""
    comparison = compared(name)
    statistics = comparison.statistics()
    assert statistics.counts.total == len(comparison.changes)
    assert comparison.to_dict()["statistics"] == statistics.to_dict()


@pytest.mark.parametrize("name", NAMES)
def test_a_run_round_trips_through_from_dict(name: str) -> None:
    """``from_dict(to_dict(include_alignment=True))`` writes the same payload."""
    data, comparison = rebuilt(name)
    assert comparison.to_dict(include_alignment=True) == data
    assert comparison.statistics() == compared(name).statistics()


@pytest.mark.parametrize("name", NAMES)
def test_the_change_list_rebuilds_from_what_the_wire_carries(name: str) -> None:
    """The order, the delete placements included, survives serialisation."""
    data, comparison = rebuilt(name)
    again = build_change_tree(comparison.alignment, comparison.source, comparison.test)
    assert [change.to_dict() for change in again] == data["changes"]


@pytest.mark.parametrize("name", NAMES)
def test_anchors_place_every_block_alike_after_the_round_trip(name: str) -> None:
    """`Anchors` reads only what the wire carries (D15, rule 7)."""
    original = compared(name)
    _, comparison = rebuilt(name)
    before = Anchors(
        source=original.source, test=original.test, alignment=original.alignment
    )
    after = Anchors(
        source=comparison.source, test=comparison.test, alignment=comparison.alignment
    )
    for block in original.source.walk():
        assert after.place(block.path) == before.place(block.path), block.path


@pytest.mark.parametrize("name", NAMES)
def test_every_anchor_names_a_child_of_its_test_parent(name: str) -> None:
    """``after`` is ``None`` or a child of ``test_parent``, for every source block.

    A sibling counts as having stayed in place only if its counterpart sits
    under the same test parent; a block that rode along inside a moved
    clause into another limb must not be one. No committed run holds that
    case (``tests/test_delete_anchor.py`` builds one by hand), so this holds
    the shape of every anchor the corpus does produce.
    """
    comparison = compared(name)
    test_parent = {
        child.path: block.path
        for block in comparison.test.walk()
        for child in block.children
    }
    placed = Anchors(
        source=comparison.source, test=comparison.test, alignment=comparison.alignment
    )
    for block in comparison.source.walk():
        anchor = placed.place(block.path)
        if anchor is not None and anchor.after is not None:
            assert test_parent[anchor.after] == anchor.test_parent, block.path


@pytest.mark.parametrize("name", NAMES)
def test_two_builds_give_identical_change_lists(name: str) -> None:
    """Comparing the same pair twice gives the same bytes (N1)."""
    run = BY_NAME[name]
    source, test = run.texts()
    again = compare(source, test, format=run.format)
    assert again.to_json(include_alignment=True) == payload(name)
