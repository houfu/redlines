"""Tests for `redlines.filters`: `ChangeFilter` and `filter_changes` (#138).

The sample pair (`tests/corpus/sample_pair`) is the fixture: its eight named
changes (`tests/corpus/sample_pair/CHANGES.md`) give every `ChangeKind` at
least one instance, a real move, a real renumber, and the segment-alignment
trap (`/section[1]` vs. `/section[11]`) the address-prefix rule exists to
guard against. `Comparison.filter()` is exercised alongside the module-level
`filter_changes`/`ChangeFilter` pair, since it is the convenience #138 asks
`Comparison` to carry.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from redlines.blocks import BlockTree
from redlines.changes import ChangeKind
from redlines.comparison import Comparison, compare
from redlines.filters import ChangeFilter, filter_changes

CASE_DIR = Path(__file__).parent / "corpus" / "sample_pair" / "expected"

# Addresses from tests/test_sample_pair_change_tree.py, spelled the same way.
CONFIDENTIAL_INFORMATION = "/section[1]/section[2]/list_item[4]"  # modify
MOVED_CLAUSE_TEST = "/section[1]/section[9]/list_item[6]"  # move
RENUMBERED_SECTION = "/section[1]/section[3]"
INSERTED_CLAUSE = f"{RENUMBERED_SECTION}/list_item[3]"  # insert
DELETED_SUB_CLAUSE = "/section[1]/section[5]/list_item[4]/list_item[3]"  # delete

_CACHE: dict[str, Comparison] = {}


def comparison() -> Comparison:
    """The sample pair, contract profile, compared once and cached."""
    if "contract" not in _CACHE:
        source = BlockTree.from_dict(
            json.loads((CASE_DIR / "source.contract.json").read_text(encoding="utf-8"))
        )
        test = BlockTree.from_dict(
            json.loads((CASE_DIR / "test.contract.json").read_text(encoding="utf-8"))
        )
        _CACHE["contract"] = compare(source, test)
    return _CACHE["contract"]


def kinds_present(comparison_: Comparison) -> set[str]:
    """Every `ChangeKind` value the sample pair's change tree actually has."""
    return {change.kind.value for change in comparison_.changes}


# --- ChangeFilter.matches / filter_changes -----------------------------------


def test_an_empty_filter_matches_everything() -> None:
    result = comparison()
    spec = ChangeFilter()

    assert all(spec.matches(change) for change in result.changes)
    assert filter_changes(result.changes, spec).changes == result.changes.changes


def test_kinds_keeps_only_the_named_kinds() -> None:
    result = comparison()
    assert kinds_present(result) >= {"insert", "delete", "modify", "move", "renumber"}
    spec = ChangeFilter(kinds=(ChangeKind.MOVE, ChangeKind.DELETE))

    filtered = filter_changes(result.changes, spec)

    assert filtered.changes
    assert {change.kind.value for change in filtered} == {"move", "delete"}


def test_kinds_accepts_plain_strings() -> None:
    """The wire spelling works directly, not only the enum members."""
    spec = ChangeFilter(kinds=("move",))  # type: ignore[arg-type]

    assert spec.kinds == (ChangeKind.MOVE,)


def test_an_unrecognised_kind_raises() -> None:
    with pytest.raises(ValueError):
        ChangeFilter(kinds=("spam",))  # type: ignore[arg-type]


def test_address_prefix_matches_the_exact_address_and_its_descendants() -> None:
    result = comparison()
    spec = ChangeFilter(address_prefixes=(RENUMBERED_SECTION,))

    filtered = filter_changes(result.changes, spec)

    addresses = {
        addr
        for change in filtered
        for addr in (change.source_address, change.test_address)
        if addr is not None
    }
    assert addresses  # the renumbers and the insert are all under here
    assert all(
        addr == RENUMBERED_SECTION or addr.startswith(RENUMBERED_SECTION + "/")
        for addr in addresses
    )


def test_address_prefix_is_segment_aligned_not_a_naive_startswith() -> None:
    """`/section[1]` must not swallow `/section[11]` -- both exist in the pair."""
    result = comparison()
    spec = ChangeFilter(address_prefixes=("/section[1]",))

    filtered = filter_changes(result.changes, spec)

    for change in filtered:
        for addr in (change.source_address, change.test_address):
            if addr is None:
                continue
            assert addr == "/section[1]" or addr.startswith("/section[1]/")
            assert not addr.startswith("/section[11]")


def test_address_prefix_matches_either_address_after_a_move() -> None:
    """A scope naming the move's OLD location still reports it (#138)."""
    result = comparison()
    move = next(c for c in result.changes if c.kind is ChangeKind.MOVE)
    old_section = move.source_address.rsplit("/", 1)[0]  # type: ignore[union-attr]
    assert move.test_address is not None and not move.test_address.startswith(
        old_section
    )
    spec = ChangeFilter(address_prefixes=(old_section,))

    filtered = filter_changes(result.changes, spec)

    assert move in filtered.changes


def test_root_path_matches_everything() -> None:
    result = comparison()
    spec = ChangeFilter(address_prefixes=("/",))

    filtered = filter_changes(result.changes, spec)

    assert filtered.changes == result.changes.changes


def test_labels_or_within_the_field() -> None:
    result = comparison()
    move = next(c for c in result.changes if c.kind is ChangeKind.MOVE)
    spec = ChangeFilter(labels=(move.test_label, "does-not-exist"))  # type: ignore[arg-type]

    filtered = filter_changes(result.changes, spec)

    assert move in filtered.changes
    assert all(
        change.source_label in spec.labels or change.test_label in spec.labels
        for change in filtered
    )


def test_roles_narrows_the_result() -> None:
    result = comparison()
    modify = next(c for c in result.changes if c.kind is ChangeKind.MODIFY)
    assert modify.role is not None
    spec = ChangeFilter(roles=(modify.role,))

    filtered = filter_changes(result.changes, spec)

    assert modify in filtered.changes
    assert all(change.role == modify.role for change in filtered)


def test_fields_and_together_narrowing_the_result() -> None:
    """Adding a second dimension can only narrow, never widen (#138)."""
    result = comparison()
    kind_only = filter_changes(result.changes, ChangeFilter(kinds=(ChangeKind.MODIFY,)))
    narrower = filter_changes(
        result.changes,
        ChangeFilter(kinds=(ChangeKind.MODIFY,), address_prefixes=(RENUMBERED_SECTION,)),
    )

    assert set(c.test_address for c in narrower) <= set(c.test_address for c in kind_only)
    assert len(narrower.changes) <= len(kind_only.changes)


def test_min_chars_zero_is_no_constraint() -> None:
    result = comparison()
    spec = ChangeFilter(min_chars=0)

    assert filter_changes(result.changes, spec).changes == result.changes.changes


def test_min_chars_drops_small_edits_and_every_insert_and_delete() -> None:
    """An insert/delete never carries inline ops, so chars_added/deleted are 0
    for them (`redlines.changes.Change`) -- `min_chars > 0` excludes them
    whatever the size of the block, which is the honest reading of "compared
    against max(chars_added, chars_deleted) for the node" (ADR-0033)."""
    result = comparison()
    spec = ChangeFilter(min_chars=1)

    filtered = filter_changes(result.changes, spec)

    assert filtered.changes
    assert all(change.kind not in (ChangeKind.INSERT, ChangeKind.DELETE) for change in filtered)
    assert all(
        max(change.chars_added, change.chars_deleted) >= 1 for change in filtered
    )


def test_min_chars_above_every_edit_empties_the_result() -> None:
    result = comparison()
    spec = ChangeFilter(min_chars=10_000)

    assert filter_changes(result.changes, spec).changes == ()


def test_min_chars_rejects_negative() -> None:
    with pytest.raises(ValueError):
        ChangeFilter(min_chars=-1)


def test_has_inline_true_is_the_edit_predicate_kind_precedence_hides() -> None:
    """A renumbered-and-edited clause is a `renumber` node; `kind == "modify"`
    alone would miss its edit, which is exactly what `has_inline` is for."""
    result = comparison()
    has_edit = filter_changes(result.changes, ChangeFilter(has_inline=True))
    only_modify = filter_changes(result.changes, ChangeFilter(kinds=(ChangeKind.MODIFY,)))

    assert all(change.has_inline for change in has_edit)
    assert set(c.test_address for c in only_modify) <= set(c.test_address for c in has_edit)


def test_has_inline_false_keeps_only_the_textless_nodes() -> None:
    result = comparison()
    spec = ChangeFilter(has_inline=False)

    filtered = filter_changes(result.changes, spec)

    assert filtered.changes
    assert all(not change.has_inline for change in filtered)


# --- to_dict / from_dict ------------------------------------------------------


def test_to_dict_round_trips_through_from_dict() -> None:
    spec = ChangeFilter(
        kinds=(ChangeKind.MODIFY, ChangeKind.MOVE),
        address_prefixes=("/section[1]",),
        labels=("2.4",),
        roles=("clause",),
        min_chars=5,
        has_inline=True,
    )

    assert ChangeFilter.from_dict(spec.to_dict()) == spec


def test_to_dict_has_the_documented_key_order() -> None:
    spec = ChangeFilter()

    assert list(spec.to_dict()) == [
        "kinds",
        "address_prefixes",
        "labels",
        "roles",
        "min_chars",
        "has_inline",
    ]


def test_from_dict_rejects_an_unknown_key() -> None:
    with pytest.raises(ValueError):
        ChangeFilter.from_dict({"spam": 1})


def test_default_filter_serialises_to_empty_constraints() -> None:
    assert ChangeFilter().to_dict() == {
        "kinds": [],
        "address_prefixes": [],
        "labels": [],
        "roles": [],
        "min_chars": 0,
        "has_inline": None,
    }


# --- Comparison.filter() -------------------------------------------------------


def test_comparison_filter_matches_the_module_level_function() -> None:
    result = comparison()

    via_method = result.filter(kinds=("move",))
    via_function = filter_changes(result.changes, ChangeFilter(kinds=("move",)))  # type: ignore[arg-type]

    assert via_method.changes.changes == via_function.changes


def test_comparison_filter_keeps_the_same_trees_and_alignment_unpruned() -> None:
    """The filtered result carries the full, unpruned block trees and the same
    alignment -- pruning them would invalidate every address a surviving
    change still names (#138)."""
    result = comparison()

    filtered = result.filter(kinds=("move",))

    assert filtered.source == result.source
    assert filtered.test == result.test
    assert filtered.alignment == result.alignment
    assert len(filtered.changes) < len(result.changes)


def test_comparison_filter_records_the_spec_on_config() -> None:
    result = comparison()

    filtered = result.filter(min_chars=1)

    assert filtered.config.filter == ChangeFilter(min_chars=1)
    assert result.config.filter is None  # the original is untouched


def test_an_unfiltered_comparisons_config_has_no_filter() -> None:
    assert comparison().config.filter is None
