"""The PRD § 3a sample pair and its expected block trees (#108).

`tests/corpus/sample_pair/` holds one short commercial services agreement
written twice — `source.md`/`test.md` and their plain-text twins
`source.txt`/`test.txt` — where the amended version carries exactly the eight
changes ADR-0013 names, one of each, and nothing else.
`tests/corpus/sample_pair/CHANGES.md` lists them with the addresses.

Two kinds of test live here.

The first is the M1 exit criterion: each input parses into the tree frozen
under ``expected/``, the markdown under the built-in ``markdown`` profile and
the plain text under ``contract``, both through
`redlines.semantic.apply_semantics`. That comparison is exact, so any change
in a reader, a profile or the semantic pass surfaces as a diff of the whole
tree.

The second states, in assertions rather than in prose, the facts the pair
exists to demonstrate: what the definitions section became, that the moved
clause kept its text, that the cross-reference followed the renumbering, that
the whitespace-only change left no trace, and that the two twins agree block
by block. A whole-tree diff is unreadable when it fails; these say which
promise broke.

The change tree for this pair is M2's golden, not this file's.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from redlines.blocks import Block, BlockKind, BlockTree
from redlines.profiles import builtin_profile
from redlines.readers import reader_for
from redlines.semantic import apply_semantics

CASE_DIR = Path(__file__).parent / "corpus" / "sample_pair"
EXPECTED_DIR = CASE_DIR / "expected"

# (input file, reader format, profile name), mirroring
# tests/corpus/sample_pair/regenerate.py. The pipeline below is written out
# again here on purpose: the goldens are only worth having if something
# rebuilds them independently and compares.
PAIRINGS: tuple[tuple[str, str, str], ...] = (
    ("source.txt", "text", "contract"),
    ("test.txt", "text", "contract"),
    ("source.md", "markdown", "markdown"),
    ("test.md", "markdown", "markdown"),
)

# The addresses CHANGES.md names, so a failure here points at a row of that
# table rather than at a path buried in a 120 KB diff.
DEFINITIONS_SECTION = "/section[1]/section[2]"
CONFIDENTIAL_INFORMATION = "/section[1]/section[2]/list_item[4]"
MOVED_CLAUSE_SOURCE = "/section[1]/section[7]/list_item[5]"
MOVED_CLAUSE_TEST = "/section[1]/section[9]/list_item[6]"
RENUMBERED_SECTION = "/section[1]/section[3]"
CROSS_REFERENCE_CLAUSE = "/section[1]/section[9]/list_item[2]"
DELETED_SUB_CLAUSE = "/section[1]/section[5]/list_item[4]"
NOTICES_CLAUSE = "/section[1]/section[11]/list_item[5]"
DELIVERABLES_TABLE = "/section[3]/list_item[3]/table[1]"
DELIVERABLES_LEAD_IN = "/section[3]/list_item[3]/paragraph[1]"
DELIVERABLES_PARAGRAPHS = "/section[3]/list_item[3]/paragraph["
REPETITIVE_SCHEDULE = "/section[4]"

# Three blocks fall through to a plain paragraph in every one of the four
# trees, and they are the same three every time: the parties recital under the
# title, and the two signature lines. None carries a label, and none sits
# under a labelled block that could adopt it as a continuation, so `fallback`
# is the honest answer rather than a parsing failure (ADR-0030). The number is
# pinned so that a reader which starts guessing at them shows up here.
EXPECTED_FALLBACKS = 3


def build_tree(path: Path, *, format: str, profile_name: str) -> BlockTree:
    """Read ``path`` with the reader for ``format`` and run the semantic pass."""
    profile = builtin_profile(profile_name)
    tree = reader_for(format).read(path.read_text(encoding="utf-8"), profile=profile)
    return apply_semantics(tree, profile)


def tree_for(input_name: str) -> BlockTree:
    """Build the tree for one of the four sample-pair inputs."""
    for name, format, profile_name in PAIRINGS:
        if name == input_name:
            return build_tree(CASE_DIR / name, format=format, profile_name=profile_name)
    raise AssertionError(f"{input_name!r} is not one of the sample-pair inputs")


def expected_dict(input_name: str, profile_name: str) -> dict[str, Any]:
    """Load the frozen tree for one input and profile."""
    path = EXPECTED_DIR / f"{Path(input_name).stem}.{profile_name}.json"
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def spans_of(block: Block) -> list[tuple[str, str | None, str]]:
    """A block's spans as (type, value, covered text) — never offsets.

    Markdown syntax moves offsets around, so the twins are compared on what a
    span says, not on where it sits.
    """
    return [
        (span.type, span.value, block.text[span.start : span.end])
        for span in block.spans
    ]


def clause_labels(section: Block) -> list[str | None]:
    """The labels of a section's clauses, ignoring its heading."""
    return [
        child.label for child in section.children if child.kind is BlockKind.LIST_ITEM
    ]


def cross_references(tree: BlockTree) -> dict[str, list[str | None]]:
    """Every cross-reference span's value, keyed by the address it sits at."""
    found: dict[str, list[str | None]] = {}
    for block in tree.walk():
        values = [span.value for span in block.spans if span.type == "cross_reference"]
        if values:
            found[block.path] = values
    return found


# --- the exit criterion: the pair parses into the expected trees ------------


@pytest.mark.parametrize(("input_name", "format", "profile_name"), PAIRINGS)
def test_the_pair_parses_into_the_expected_tree(
    input_name: str, format: str, profile_name: str
) -> None:
    """ROADMAP § M1's exit criterion, one input at a time.

    If this fails and the change is intentional, regenerate with
    ``uv run python tests/corpus/sample_pair/regenerate.py`` and read the diff.
    """
    tree = build_tree(CASE_DIR / input_name, format=format, profile_name=profile_name)

    assert tree.to_dict() == expected_dict(input_name, profile_name)


@pytest.mark.parametrize(("input_name", "format", "profile_name"), PAIRINGS)
def test_the_expected_tree_round_trips_through_json(
    input_name: str, format: str, profile_name: str
) -> None:
    """The goldens are the wire format too: `from_dict` rebuilds them exactly."""
    data = expected_dict(input_name, profile_name)

    assert BlockTree.from_dict(data).to_dict() == data


@pytest.mark.parametrize(("input_name", "format", "profile_name"), PAIRINGS)
def test_reading_the_same_input_twice_gives_the_same_tree(
    input_name: str, format: str, profile_name: str
) -> None:
    """Determinism (N1): no dict or set ordering leaks into the output."""
    first = build_tree(CASE_DIR / input_name, format=format, profile_name=profile_name)
    second = build_tree(CASE_DIR / input_name, format=format, profile_name=profile_name)

    assert first == second


def test_the_case_directory_is_complete() -> None:
    """A half-added pair (a missing twin or golden) must fail loudly."""
    missing = [
        name
        for name in ["source.md", "test.md", "source.txt", "test.txt", "CHANGES.md"]
        + [
            f"expected/{Path(input_name).stem}.{profile_name}.json"
            for input_name, _, profile_name in PAIRINGS
        ]
        if not (CASE_DIR / name).is_file()
    ]

    assert not missing, f"The sample pair is missing {missing}."


# --- what the readers made of it -------------------------------------------


@pytest.mark.parametrize("input_name", [name for name, _, _ in PAIRINGS])
def test_only_the_recital_and_the_signatures_fall_back(input_name: str) -> None:
    """Three fallbacks, and they are the three named in ``EXPECTED_FALLBACKS``."""
    tree = tree_for(input_name)

    fallbacks = [block for block in tree.walk() if block.matched_by == "fallback"]
    assert tree.fallback_count == EXPECTED_FALLBACKS
    assert len(fallbacks) == EXPECTED_FALLBACKS
    assert fallbacks[0].text.startswith("This Agreement is made on 1 March 2026")
    assert [block.path for block in fallbacks[1:]] == [
        "/section[2]/paragraph[1]",
        "/section[2]/paragraph[2]",
    ]
    assert all(
        block.text.startswith("Signed for and on behalf of") for block in fallbacks[1:]
    )


@pytest.mark.parametrize("input_name", [name for name, _, _ in PAIRINGS])
def test_nothing_is_dropped(input_name: str) -> None:
    """R3: the pair contains nothing either reader has to throw away, so the
    dropped report is empty rather than merely small."""
    assert tree_for(input_name).dropped == ()


@pytest.mark.parametrize("input_name", [name for name, _, _ in PAIRINGS])
def test_the_definitions_section_carries_its_roles_and_defined_terms(
    input_name: str,
) -> None:
    """PRD § 6b's semantic pass, on the section the pair was written around."""
    tree = tree_for(input_name)
    section = tree.block_at(DEFINITIONS_SECTION)
    heading, *definitions = section.children

    assert section.role == "definitions"
    assert heading.kind is BlockKind.HEADING
    assert heading.text == "Definitions"
    assert [block.role for block in definitions] == ["definition"] * 8
    assert [block.label for block in definitions] == [
        f"2.{number}" for number in range(1, 9)
    ]

    confidential = tree.block_at(CONFIDENTIAL_INFORMATION)
    assert confidential.role == "definition"
    assert ("defined_term", None, "Confidential Information") in spans_of(confidential)


@pytest.mark.parametrize("input_name", [name for name, _, _ in PAIRINGS])
def test_the_schedules_restart_their_numbering(input_name: str) -> None:
    """A PRD § 6b hard case, in the sample pair rather than only in a fixture:
    the body runs to 11.6 and Schedule 1 starts again at 1."""
    tree = tree_for(input_name)
    last_body_clause = tree.block_at("/section[1]/section[11]/list_item[6]")
    schedule_heading = tree.block_at("/section[3]/heading[1]")
    first_schedule_item = tree.block_at("/section[3]/list_item[1]")

    assert last_body_clause.label == "11.6"
    assert schedule_heading.label == "Schedule 1"
    assert schedule_heading.role == "schedule"
    assert first_schedule_item.label == "1"
    assert first_schedule_item.role == "schedule"


# --- the eight changes ------------------------------------------------------


@pytest.mark.parametrize("suffix", [".txt", ".md"])
def test_change_1_the_definition_text_changed_in_place(suffix: str) -> None:
    source = tree_for("source" + suffix).block_at(CONFIDENTIAL_INFORMATION)
    amended = tree_for("test" + suffix).block_at(CONFIDENTIAL_INFORMATION)

    assert source.label == amended.label == "2.4"
    assert source.role == amended.role == "definition"
    assert source.text != amended.text
    assert amended.text.endswith("ought reasonably to treat as confidential.")
    # Still one definition of the same term, not a new one.
    assert spans_of(source)[0] == spans_of(amended)[0]


@pytest.mark.parametrize("suffix", [".txt", ".md"])
def test_change_2_the_moved_clause_keeps_its_text_at_a_new_address(
    suffix: str,
) -> None:
    """The clause itself is byte-identical; the edit is in the body attached to
    it. That is what makes the move separable from the edit."""
    source = tree_for("source" + suffix).block_at(MOVED_CLAUSE_SOURCE)
    amended = tree_for("test" + suffix).block_at(MOVED_CLAUSE_TEST)

    assert source.path != amended.path
    assert (source.label, amended.label) == ("7.5", "9.6")
    assert source.text == amended.text
    assert source.text.startswith("Each party shall return or destroy")

    source_body, amended_body = source.children[0], amended.children[0]
    assert source_body.matched_by == amended_body.matched_by == "continuation"
    assert "three years" in source_body.text
    assert "five years" in amended_body.text


@pytest.mark.parametrize("suffix", [".txt", ".md"])
def test_change_3_the_inserted_clause_renumbers_the_two_below_it(
    suffix: str,
) -> None:
    source = tree_for("source" + suffix).block_at(RENUMBERED_SECTION)
    amended = tree_for("test" + suffix).block_at(RENUMBERED_SECTION)

    assert clause_labels(source) == ["3.1", "3.2", "3.3", "3.4"]
    assert clause_labels(amended) == ["3.1", "3.2", "3.3", "3.4", "3.5"]
    # One clause is new; the other two kept their text and changed their label.
    assert amended.children[3].text.startswith(
        "The Supplier may engage a subcontractor"
    )
    assert amended.children[4].text == source.children[3].text
    assert amended.children[5].text == source.children[4].text


@pytest.mark.parametrize("suffix", [".txt", ".md"])
def test_change_4_the_cross_reference_follows_the_renumbering(suffix: str) -> None:
    """The only cross-reference in the document whose value moved, and it moved
    to exactly where the inserted clause pushed its target."""
    source, amended = tree_for("source" + suffix), tree_for("test" + suffix)

    assert cross_references(source)[CROSS_REFERENCE_CLAUSE] == ["3.3"]
    assert cross_references(amended)[CROSS_REFERENCE_CLAUSE] == ["3.4"]

    differing = {
        path
        for path in set(cross_references(source)) & set(cross_references(amended))
        if cross_references(source)[path] != cross_references(amended)[path]
    }
    assert differing == {CROSS_REFERENCE_CLAUSE}


@pytest.mark.parametrize("suffix", [".txt", ".md"])
def test_change_5_the_deleted_sub_clause_leaves_its_siblings_alone(
    suffix: str,
) -> None:
    source = tree_for("source" + suffix).block_at(DELETED_SUB_CLAUSE)
    amended = tree_for("test" + suffix).block_at(DELETED_SUB_CLAUSE)

    assert [child.label for child in source.children] == ["(a)", "(b)", "(c)"]
    assert [child.label for child in amended.children] == ["(a)", "(b)"]
    assert [child.text for child in amended.children] == [
        child.text for child in source.children[:2]
    ]


def test_change_6_the_markdown_table_gains_a_row() -> None:
    source = tree_for("source.md").block_at(DELIVERABLES_TABLE)
    amended = tree_for("test.md").block_at(DELIVERABLES_TABLE)

    assert len(amended.children) == len(source.children) + 1
    assert [cell.text for cell in amended.children[4].children] == [
        "Training day",
        "Week 9",
        "Client",
    ]
    # The header row and the rows above the insertion are untouched.
    assert [cell.text for cell in amended.children[0].children] == [
        "Deliverable",
        "Due by",
        "Owner",
    ]
    assert amended.children[0].attrs["header"] is True
    assert [[cell.text for cell in row.children] for row in amended.children[:4]] == [
        [cell.text for cell in row.children] for row in source.children[:4]
    ]


def test_change_6_the_plain_text_twin_gains_a_deliverable_paragraph() -> None:
    """The one place the twins diverge, stated rather than hidden.

    A pipe table is markdown syntax and the plain-text reader has no table
    support (ADR-0013), so the text twin writes the deliverables as sentences
    and the inserted row is an inserted paragraph. CHANGES.md § 6 explains the
    choice; `test_the_twins_agree_block_by_block` sets exactly this subtree
    aside and nothing else.
    """
    source = tree_for("source.txt").block_at("/section[3]/list_item[3]")
    amended = tree_for("test.txt").block_at("/section[3]/list_item[3]")

    assert len(amended.children) == len(source.children) + 1
    assert amended.children[4].text.startswith("The training day is due by Week 9")
    assert all(child.kind is BlockKind.PARAGRAPH for child in amended.children)


@pytest.mark.parametrize("suffix", [".txt", ".md"])
def test_change_7_the_whitespace_only_change_is_no_change_at_all(
    suffix: str,
) -> None:
    """Clause 11.5 is hard-wrapped at different points in the two versions. The
    readers re-join hard wraps, so the change never reaches the tree."""
    source = tree_for("source" + suffix).block_at(NOTICES_CLAUSE)
    amended = tree_for("test" + suffix).block_at(NOTICES_CLAUSE)

    assert source.label == amended.label == "11.5"
    assert source.text == amended.text
    assert "\n" not in source.text
    # And the two files really do differ, or this would prove nothing.
    assert (CASE_DIR / ("source" + suffix)).read_text(encoding="utf-8") != (
        CASE_DIR / ("test" + suffix)
    ).read_text(encoding="utf-8")


@pytest.mark.parametrize("suffix", [".txt", ".md"])
def test_change_8_only_one_item_of_the_repetitive_schedule_moved(
    suffix: str,
) -> None:
    """Schedule 2 is eight near-identical service-level clauses — the shape the
    flat engine loses an edit in (ADR-0010). Exactly one of them differs."""
    source = tree_for("source" + suffix).block_at(REPETITIVE_SCHEDULE)
    amended = tree_for("test" + suffix).block_at(REPETITIVE_SCHEDULE)
    differing = [
        (before.label, after.label)
        for before, after in zip(source.children, amended.children)
        if before.text != after.text
    ]

    assert len(source.children) == len(amended.children)
    assert differing == [("3", "3")]
    assert "within two hours" in amended.children[3].text
    assert "within four hours" in source.children[3].text


# --- the twins --------------------------------------------------------------


def twin_spine(tree: BlockTree, *, markdown: bool) -> list[Block]:
    """Every block except the deliverables table and its plain-text stand-in.

    The markdown table subtree (`table` > `row` > `cell`) and the paragraphs
    the text twin states the same deliverables in are the one region where the
    two formats cannot produce the same shape, because the plain-text reader
    has no tables. Everything else is compared.
    """
    spine = []
    for block in tree.walk():
        if markdown and block.path.startswith(DELIVERABLES_TABLE):
            continue
        if (
            not markdown
            and block.path.startswith(DELIVERABLES_PARAGRAPHS)
            and block.path != DELIVERABLES_LEAD_IN
        ):
            continue
        spine.append(block)
    return spine


@pytest.mark.parametrize("stem", ["source", "test"])
def test_the_twins_agree_block_by_block(stem: str) -> None:
    """PRD § 6b's promise on the document the milestone ships: a markdown
    contract with ``## 7. Termination`` and numbered clauses gets the same
    kinds, labels, levels and roles as its plain-text twin."""
    plain = twin_spine(tree_for(stem + ".txt"), markdown=False)
    marked = twin_spine(tree_for(stem + ".md"), markdown=True)

    assert len(plain) == len(marked)
    assert [(block.kind, block.label, block.level, block.role) for block in plain] == [
        (block.kind, block.label, block.level, block.role) for block in marked
    ]


@pytest.mark.parametrize("stem", ["source", "test"])
def test_the_twins_carry_the_same_spans(stem: str) -> None:
    """Spans by type and value, never by offset: markdown syntax moves offsets,
    and the pair must not depend on that."""
    plain = twin_spine(tree_for(stem + ".txt"), markdown=False)
    marked = twin_spine(tree_for(stem + ".md"), markdown=True)

    assert [spans_of(block) for block in plain] == [spans_of(block) for block in marked]


@pytest.mark.parametrize("stem", ["source", "test"])
def test_the_twins_carry_the_same_text(stem: str) -> None:
    """They are the same agreement written twice, so once the syntax is off the
    blocks say the same words — hard-wrapped clauses included."""
    plain = twin_spine(tree_for(stem + ".txt"), markdown=False)
    marked = twin_spine(tree_for(stem + ".md"), markdown=True)

    assert [block.text for block in plain] == [block.text for block in marked]


@pytest.mark.parametrize("stem", ["source", "test"])
def test_the_twins_differ_only_in_how_they_were_recognised(stem: str) -> None:
    """What the twins do *not* share, recorded so it is a decision and not a
    surprise: the markdown reader says the syntax told it (``markdown:atx``,
    ``markdown:list``), the text reader says a profile pattern did
    (``label:decimal``). ADR-0030 makes ``matched_by`` the rule that fired, so
    two readers reaching the same block by different routes must differ here.
    """
    plain = twin_spine(tree_for(stem + ".txt"), markdown=False)
    marked = twin_spine(tree_for(stem + ".md"), markdown=True)
    disagreements = {
        (before.matched_by, after.matched_by)
        for before, after in zip(plain, marked)
        if before.matched_by != after.matched_by
    }

    assert disagreements == {
        ("heading:score", "markdown:atx"),
        ("label:decimal", "markdown:atx"),
        ("label:decimal", "markdown:list"),
        ("heading:schedule", "markdown:atx"),
    }
