"""``Comparison.output_rich``: the test document marked in place, for a terminal (#180, ADR-0037).

0.6's two colours over the change tree, with the notes a tree can give: an
insertion ``green``, a deletion ``strike red``, a move drawn where it is now
with a ``magenta`` note and a ``magenta`` tombstone where it was, headings
bold and roles off, under a header line of counts and yellow notices.

The goldens are ``(plain, spans)`` as JSON rather than ``Text.markup``, which
churns on rich upgrades. Everything here goes through the public method.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from rich.text import Text

from redlines.alignment import AlignmentConfig
from redlines.blocks import Block, BlockKind, BlockTree
from redlines.comparison import Comparison, compare
from redlines.renderers._inplace import layout, serialize
from redlines.renderers._marks import RICH
from tests.helpers.hash_seed import assert_byte_identical_across_hash_seeds

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE = REPO_ROOT / "tests" / "corpus" / "sample_pair"
CASES = REPO_ROOT / "tests" / "renderer_cases"
GOLDEN_ALIGNMENT = AlignmentConfig(similarity="difflib")  # the goldens' backend


def read(path: Path) -> str:
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def case(name: str) -> Comparison:
    return compare(
        read(CASES / name / "source.md"),
        read(CASES / name / "test.md"),
        format="markdown",
        alignment=GOLDEN_ALIGNMENT,
    )


def sample_markdown() -> Comparison:
    return compare(
        read(SAMPLE / "source.md"),
        read(SAMPLE / "test.md"),
        format="markdown",
        profile="markdown",
        alignment=GOLDEN_ALIGNMENT,
    )


def runs(text: Text) -> list[tuple[str, str]]:
    """Each span as the text it covers and its style."""
    return [(text.plain[span.start : span.end], str(span.style)) for span in text.spans]


def as_golden(text: Text) -> dict[str, object]:
    return {
        "plain": text.plain,
        "spans": [[span.start, span.end, str(span.style)] for span in text.spans],
    }


def dump(text: Text) -> str:
    """The goldens' JSON layout, written out again: one span to a line, a trailing newline."""
    spans = [[span.start, span.end, str(span.style)] for span in text.spans]
    rows = ",\n".join("    " + json.dumps(span, ensure_ascii=False) for span in spans)
    return (
        '{\n  "plain": '
        + json.dumps(text.plain, ensure_ascii=False)
        + ',\n  "spans": [\n'
        + (rows + "\n" if rows else "")
        + "  ]\n}\n"
    )


@pytest.fixture(scope="module")
def four_kinds() -> Comparison:
    return case("four_kinds")


# --- the goldens --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("golden", "build"),
    [
        (SAMPLE / "expected" / "rendered" / "rich.markdown.json", sample_markdown),
        (CASES / "four_kinds" / "rich.json", lambda: case("four_kinds")),
    ],
    ids=["sample_pair/rich.markdown.json", "four_kinds/rich.json"],
)
def test_the_rendering_is_its_golden(
    golden: Path, build: Callable[[], Comparison]
) -> None:
    rendered = build().output_rich()
    written = read(golden)
    assert json.loads(written) == as_golden(rendered)
    assert written == dump(rendered)


def test_the_four_kinds_are_styled_run_by_run(four_kinds: Comparison) -> None:
    """#180's layout, span by span: 0.6's two styles, notes magenta, headings bold."""
    text = four_kinds.output_rich()
    assert text.plain.split("\n\n") == [
        "4 changes: 1 inserted, 1 deleted, 1 modified, 1 moved, 0 renumbered",
        "1. Delivery",
        "1.1 The Supplier shall deliver the goods within thirty (30sixty (60) days of each order.",
        "1.2 moved to 2.2 /section[2]/list_item[2]",
        "1.2 The Buyer may reject goods that do not match the order.",
        "2. Payment",
        "2.1 The Buyer shall pay each invoice within fourteen days of receiving it.",
        "2.2 Late payments carry interest at two per cent a month.",
        "1.2 2.2 Risk in the goods passes to the Buyer when the goods are unloaded at the "
        "Buyer's warehouse. moved from 1.2 /section[1]/list_item[2]",
    ]
    assert runs(text) == [
        ("4 changes", "bold"),
        ("1. Delivery", "bold"),
        ("thirty (30", "strike red"),
        ("sixty (60", "green"),
        ("1.2 moved to 2.2 /section[2]/list_item[2]", "magenta"),
        ("1.2 The Buyer may reject goods that do not match the order.", "green"),
        ("2. Payment", "bold"),
        ("2.2 Late payments carry interest at two per cent a month.", "strike red"),
        ("1.2 ", "strike red"),
        ("2.2 ", "green"),
        ("moved from 1.2 /section[1]/list_item[2]", "magenta"),
    ]


def test_a_nested_move_draws_the_inner_tombstone_inside_the_destination() -> None:
    """The tombstone stands for the moved block alone; its descendants are at its destination."""
    lines = case("nested_move").output_rich().plain.split("\n\n")[1:]
    assert lines[1:7] == [
        "7.1 Each party shall keep the other party's Confidential Information secret and use it only for this Agreement.",
        "7.2 moved to 8.2 /section[2]/list_item[2]",
        "8. Termination",
        "8.1 Either party may terminate this Agreement on ninety days' written notice to the other party.",
        "7.2 8.2 Each party shall return or destroy the other party's Confidential Information on "
        "written request. moved from 7.2 /section[1]/list_item[2]",
        "(a) The receiving party shall certify the destruction in writing within five Business Days.",
    ]
    assert "(b) moved to 9.2 /section[3]/list_item[2]" in lines


# --- the header ---------------------------------------------------------------------------


def test_the_header_counts_are_the_statistics(four_kinds: Comparison) -> None:
    sample = sample_markdown()
    for comparison in (four_kinds, sample, case("hostile")):
        counts = comparison.statistics().counts
        header = comparison.output_rich().plain.split("\n")[0]
        assert header == (
            f"{counts.total} changes: {counts.inserted} inserted, {counts.deleted} deleted, "
            f"{counts.modified} modified, {counts.moved} moved, {counts.renumbered} renumbered"
        )
    assert sample.output_rich().plain.startswith(
        "10 changes: 2 inserted, 1 deleted, 4 modified, 1 moved, 2 renumbered\n\n"
    )


def test_one_change_is_singular_and_none_is_plural() -> None:
    one = compare("A short clause.", "A shorter clause.", format="text").output_rich()
    assert (
        one.plain.split("\n")[0]
        == "1 change: 0 inserted, 0 deleted, 1 modified, 0 moved, 0 renumbered"
    )
    assert runs(one)[0] == ("1 change", "bold")
    none = compare("Same text.", "Same text.", format="text").output_rich()
    assert (
        none.plain
        == "0 changes: 0 inserted, 0 deleted, 0 modified, 0 moved, 0 renumbered\n\nSame text."
    )
    assert runs(none) == [("0 changes", "bold")]


DROPPING_SOURCE = "Intro.\n\n***\n\nThe first clause stays.\n"
DROPPING_TEST = "Intro.\n\n***\n\nThe first clause stays, edited.\n"


def _notices(text: Text) -> list[str]:
    """The header's yellow lines."""
    return [covered for covered, style in runs(text) if style == "yellow"]


def test_the_notices_appear_exactly_when_true_in_order() -> None:
    plain = compare("One clause.", "One clause, edited.", format="text")
    assert _notices(plain.output_rich()) == []
    assert _notices(plain.filter().output_rich()) == []  # a filter with no field set
    dropping = compare(DROPPING_SOURCE, DROPPING_TEST, format="markdown")
    reason = dropping.source.dropped[0].reason
    dropped = [
        f"1 thematic_break dropped from the source: {reason}",
        f"1 thematic_break dropped from the test: {reason}",
    ]
    assert _notices(dropping.output_rich()) == dropped
    filtered = dropping.filter(kinds=("modify", "insert"), min_chars=1, has_inline=True)
    stopped = dataclasses.replace(
        filtered, config=dataclasses.replace(filtered.config, budget_exhausted=True)
    )
    text = stopped.output_rich()
    assert _notices(text) == [
        "Filtered: kinds=modify,insert; min_chars=1; has_inline=true",
        "Alignment stopped early: the comparison budget ran out",
        *dropped,
    ]
    header, document = text.plain.split("\n\n", 1)
    assert header.split("\n")[1:] == _notices(text)
    assert document.startswith("Intro.")


def test_a_real_exhausted_budget_is_noticed() -> None:
    source = "\n\n".join(
        f"Clause {n} says a thing of its own, number {n}." for n in range(30)
    )
    test = "\n\n".join(
        f"Clause {n} says a thing of its own, number {n + 1}." for n in range(30)
    )
    comparison = compare(
        source,
        test,
        format="text",
        alignment=AlignmentConfig(similarity="difflib", max_comparisons=1),
    )
    assert comparison.config.budget_exhausted
    assert "Alignment stopped early: the comparison budget ran out" in _notices(
        comparison.output_rich()
    )


# --- what is and is not drawn -------------------------------------------------------------


def test_document_text_that_looks_like_markup_stays_literal() -> None:
    comparison = compare(
        "Write [bold] x and [red]y[/red].",
        "Write [bold] x and [red]z[/red].",
        format="text",
    )
    text = comparison.output_rich()
    assert "Write [bold] x and [red]" in text.plain
    assert ("Write [bold] x and [red]", "bold") not in runs(text)
    assert [style for _, style in runs(text)] == ["bold", "strike red", "green"]


def test_headings_are_bold_and_no_role_is_shown() -> None:
    comparison = sample_markdown()
    text = comparison.output_rich()
    bold = [covered for covered, style in runs(text) if style.startswith("bold")]
    headings = [
        block for block in comparison.test.walk() if block.kind is BlockKind.HEADING
    ]
    assert headings and len(bold) == len(headings) + 1  # and the total
    assert "[clause]" not in text.plain and "[definition]" not in text.plain
    assert any(block.role for block in comparison.test.walk())
    assert not any(
        line.startswith(("#", "- ", "> ", "| ---")) for line in text.plain.split("\n")
    )


def test_a_heading_carries_its_mark_in_bold() -> None:
    source = tree(
        Block(kind=BlockKind.HEADING, text="Fees", label="4", attrs={"label_raw": "4."})
    )
    text = compare(source, tree()).output_rich()
    assert runs(text)[1:] == [("4. Fees", "bold strike red")]
    inserted = compare(tree(), source).output_rich()
    assert runs(inserted)[1:] == [("4. Fees", "bold green")]


def tree(*blocks: Block) -> BlockTree:
    return BlockTree.build(Block(kind=BlockKind.DOCUMENT, children=blocks))


def test_no_run_is_empty() -> None:
    """An all-empty inserted row's empty mark writes nothing; rich versions differ on empty spans."""
    table = "| Item | Due |\n| --- | --- |\n| Setup | Week 1 |\n"
    text = compare(table, table + "|  |  |\n", format="markdown").output_rich()
    assert all(span.end > span.start for span in text.spans)
    for name in (
        "four_kinds",
        "hostile",
        "nested_move",
        "trailing_insert",
        "moved_neighbour",
    ):
        assert all(span.end > span.start for span in case(name).output_rich().spans)


def test_the_document_is_the_rich_set_spelled_as_text() -> None:
    """Below the header, the plain text is the in-place traversal with RICH's empty delimiters."""
    for comparison in (sample_markdown(), case("hostile"), case("nested_move")):
        plain = comparison.output_rich().plain
        chunks = [
            chunk
            for chunk in layout(comparison, RICH, syntax="text", roles=False)
            if chunk.block is not None  # the header notes are the rich header's
        ]
        assert plain.split("\n\n", 1)[1] == serialize(chunks, RICH, roles=False)


def test_a_filtered_comparison_marks_only_its_own_nodes(four_kinds: Comparison) -> None:
    text = four_kinds.filter(kinds=("delete",)).output_rich()
    assert [style for _, style in runs(text) if style != "bold"] == [
        "yellow",
        "strike red",
    ]
    assert "moved" not in text.plain.split("\n", 2)[2]
    assert (
        text.plain.split("\n")[0]
        == "1 change: 0 inserted, 1 deleted, 0 modified, 0 moved, 0 renumbered"
    )


# --- determinism --------------------------------------------------------------------------


def test_two_renders_and_a_round_trip_give_the_same_text(
    four_kinds: Comparison,
) -> None:
    first, second = four_kinds.output_rich(), four_kinds.output_rich()
    assert as_golden(first) == as_golden(second)
    rebuilt = Comparison.from_dict(four_kinds.to_dict(include_alignment=True))
    assert as_golden(rebuilt.output_rich()) == as_golden(first)


def test_the_sample_pair_renders_the_same_text_under_every_hash_seed() -> None:
    script = """
import json
import sys
from pathlib import Path
from redlines.alignment import AlignmentConfig
from redlines.comparison import compare
sample = Path("tests/corpus/sample_pair")
for ext, fmt in (("md", "markdown"), ("txt", "text")):
    source = (sample / f"source.{ext}").read_text(encoding="utf-8")
    test = (sample / f"test.{ext}").read_text(encoding="utf-8")
    text = compare(source, test, format=fmt, alignment=AlignmentConfig(similarity="difflib")).output_rich()
    spans = [[span.start, span.end, str(span.style)] for span in text.spans]
    sys.stdout.write(json.dumps([text.plain, spans], ensure_ascii=False) + "\\n")
"""
    output = assert_byte_identical_across_hash_seeds(script, cwd=REPO_ROOT)
    assert output.count("\n") == 2 and "magenta" in output
