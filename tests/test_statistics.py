"""Tests for `redlines.statistics`: `ChangeCounts`, `SectionStatistics` and
`ComparisonStatistics` (#139).

The sample pair is the fixture, for the same reason `tests/test_filters.py`
uses it: its change tree has one of each `ChangeKind`, a real move and a real
renumber, and a nested section structure (`/section[1]` wraps eleven numbered
sections) that is exactly the shape #139's "top-level section" reading has to
get right (see `redlines/statistics.py`'s module docstring and the
`redlines.filters` sibling module for the same reinterpretation stated in the
#138/#139/#140 PR body).

Numbers asserted below were read off `Comparison.statistics()`'s own output
for this fixture, not invented -- a whole-tree count is fragile to assert by
hand, so the properties that must hold (totals reconcile, no double
counting, deleted sections carry zero density) are what is pinned exactly;
the section-by-section table is pinned too, because it is small enough to be
a genuine golden and a change to it is exactly the kind of regression this
module exists to catch.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from redlines.blocks import BlockTree
from redlines.changes import ChangeKind
from redlines.comparison import Comparison, compare
from redlines.statistics import ChangeCounts, ComparisonStatistics, SectionStatistics

CASE_DIR = Path(__file__).parent / "corpus" / "sample_pair" / "expected"

_CACHE: dict[str, Comparison] = {}


def comparison(profile_name: str = "contract") -> Comparison:
    """The sample pair, one profile, compared once and cached."""
    if profile_name not in _CACHE:
        stem = "contract" if profile_name == "contract" else "markdown"
        source = BlockTree.from_dict(
            json.loads((CASE_DIR / f"source.{stem}.json").read_text(encoding="utf-8"))
        )
        test = BlockTree.from_dict(
            json.loads((CASE_DIR / f"test.{stem}.json").read_text(encoding="utf-8"))
        )
        _CACHE[profile_name] = compare(source, test)
    return _CACHE[profile_name]


# --- ChangeCounts -------------------------------------------------------------


def test_change_counts_tallies_every_kind() -> None:
    result = comparison()
    counts = result.statistics().counts

    assert counts.total == len(result.changes)
    assert counts.total == (
        counts.inserted
        + counts.deleted
        + counts.modified
        + counts.moved
        + counts.renumbered
    )


def test_change_counts_are_change_nodes_not_blocks() -> None:
    """A deleted sub-clause with three lettered children is one `deleted`
    node, not four (ADR-0033's topmost-wins granularity)."""
    result = comparison()
    deletes = [c for c in result.changes if c.kind is ChangeKind.DELETE]

    assert result.statistics().counts.deleted == len(deletes) == 1


def test_change_counts_inline_op_kinds_sum_to_every_inline_op() -> None:
    result = comparison()
    counts = result.statistics().counts
    total_ops = sum(len(change.inline) for change in result.changes)

    assert (
        counts.inline_insertions + counts.inline_deletions + counts.inline_replacements
        == total_ops
    )


def test_change_counts_tokens_and_chars_match_the_change_nodes() -> None:
    result = comparison()
    counts = result.statistics().counts

    assert counts.tokens_changed == sum(c.tokens_changed for c in result.changes)
    assert counts.chars_added == sum(c.chars_added for c in result.changes)
    assert counts.chars_deleted == sum(c.chars_deleted for c in result.changes)


def test_change_counts_to_dict_round_trips() -> None:
    counts = ChangeCounts(inserted=1, modified=2, total=3, tokens_changed=5)

    assert ChangeCounts.from_dict(counts.to_dict()) == counts


def test_change_counts_default_is_all_zero() -> None:
    counts = ChangeCounts()

    assert counts.to_dict() == {
        "inserted": 0,
        "deleted": 0,
        "modified": 0,
        "moved": 0,
        "renumbered": 0,
        "total": 0,
        "inline_insertions": 0,
        "inline_deletions": 0,
        "inline_replacements": 0,
        "tokens_changed": 0,
        "chars_added": 0,
        "chars_deleted": 0,
    }


# --- ComparisonStatistics: whole-comparison invariants -------------------------


def test_block_counts_match_walking_the_trees() -> None:
    result = comparison()
    stats = result.statistics()

    assert stats.source_blocks == sum(1 for _ in result.source.walk())
    assert stats.test_blocks == sum(1 for _ in result.test.walk())


def test_comparison_statistics_is_available_as_a_method_and_a_function() -> None:
    from redlines.statistics import statistics as statistics_fn

    result = comparison()

    assert result.statistics() == statistics_fn(result)


def test_statistics_is_recomputed_not_cached() -> None:
    """Two calls build an equal, independently-computed value."""
    result = comparison()

    assert result.statistics() == result.statistics()
    assert result.statistics() is not result.statistics()


# --- SectionStatistics: the section unit and its attribution -------------------


def test_every_section_row_is_a_heading_bearing_section_unit() -> None:
    """Not literally #139's "top-level section": every `section` block with a
    `heading` child, wherever it sits (ADR-0033's reinterpretation)."""
    result = comparison()
    stats = result.statistics()

    assert len(stats.sections) > 4  # more than just the four true top-level ones
    for section in stats.sections:
        assert section.heading  # every row genuinely has a heading


def test_section_counts_sum_to_the_overall_total_no_double_counting() -> None:
    """Nearest-enclosing attribution: a change is never counted at more than
    one level of nesting."""
    result = comparison()
    stats = result.statistics()

    assert sum(section.counts.total for section in stats.sections) == stats.counts.total


def test_the_outer_wrapper_section_reports_only_its_own_title_and_parties(
) -> None:
    """`/section[1]` is the whole body (eleven numbered sections beneath it);
    under nearest-enclosing attribution it reports nothing of theirs."""
    result = comparison()
    stats = result.statistics()
    wrapper = next(s for s in stats.sections if s.address == "/section[1]")

    assert wrapper.heading == "Master Services Agreement"
    assert wrapper.counts.total == 0


def test_the_renumbered_section_reports_its_own_insert_and_renumbers() -> None:
    result = comparison()
    stats = result.statistics()
    renumbered = next(
        s for s in stats.sections if s.address == "/section[1]/section[3]"
    )

    assert renumbered.counts.inserted == 1
    assert renumbered.counts.renumbered == 2
    assert renumbered.counts.total == 3


def test_density_is_total_over_blocks_rounded_to_four_places() -> None:
    result = comparison()
    stats = result.statistics()

    for section in stats.sections:
        if section.blocks:
            assert section.density == round(section.counts.total / section.blocks, 4)
        else:
            assert section.density == 0.0


def test_sections_are_in_document_order() -> None:
    result = comparison()
    stats = result.statistics()
    test_order = {block.path: i for i, block in enumerate(result.test.walk())}

    positions = [test_order[s.address] for s in stats.sections if s.address in test_order]

    assert positions == sorted(positions)


def test_breadcrumb_matches_the_tree_for_a_nested_section() -> None:
    result = comparison()
    stats = result.statistics()
    nested = next(
        s for s in stats.sections if s.address == "/section[1]/section[3]"
    )

    assert nested.breadcrumb == result.test.heading_breadcrumb(
        "/section[1]/section[3]"
    )


# --- Denominators come from the unfiltered trees -------------------------------


def test_filtering_only_shrinks_numerators_not_denominators() -> None:
    """ADR-0033: "denominators always come from the unfiltered trees"."""
    result = comparison()
    full = result.statistics()

    filtered = result.filter(kinds=("renumber",))
    filtered_stats = filtered.statistics()

    assert filtered_stats.source_blocks == full.source_blocks
    assert filtered_stats.test_blocks == full.test_blocks
    for before, after in zip(
        sorted(full.sections, key=lambda s: s.address),
        sorted(filtered_stats.sections, key=lambda s: s.address),
    ):
        assert before.address == after.address
        assert before.blocks == after.blocks
    assert filtered_stats.counts.total <= full.counts.total
    assert filtered_stats.counts.total == filtered_stats.counts.renumbered


# --- to_dict / from_dict --------------------------------------------------------


def test_comparison_statistics_round_trips_through_dict() -> None:
    result = comparison()
    stats = result.statistics()

    assert ComparisonStatistics.from_dict(stats.to_dict()) == stats


def test_section_statistics_round_trips_through_dict() -> None:
    section = SectionStatistics(
        address="/section[1]",
        heading="General",
        breadcrumb=("Master Services Agreement",),
        blocks=6,
        counts=ChangeCounts(inserted=1, total=1),
        density=0.1667,
    )

    assert SectionStatistics.from_dict(section.to_dict()) == section


def test_comparison_statistics_key_order() -> None:
    result = comparison()

    assert list(result.statistics().to_dict()) == [
        "counts",
        "source_blocks",
        "test_blocks",
        "sections",
    ]
