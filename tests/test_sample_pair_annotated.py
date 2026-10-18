"""The sample pair's annotated view against ADR-0037's checklist (#181, decision D10).

``tests/corpus/sample_pair`` is the PRD § 3a demo pair: eight changes, one of
each thing the engine is meant to detect, which M2 turns into ten change nodes
(``CHANGES.md``). Its annotated view, ``Comparison.output_annotated()``, is the
milestone's "annotated view of the sample pair reads correctly". houfu reads
the golden ``expected/rendered/annotated.markdown.md`` and approves it in a
review; this file is the machine half of the check. Each row of ADR-0037's
checklist is a named test, run on both twins unless the row says otherwise:

- P1 to P6, the properties of the whole view;
- rows 1 to 8, the eight changes of PRD § 3a in its order, each with the
  strings the view must contain and must not.

Both twins are compared exactly as their goldens were generated: under the
twin's own profile (``markdown``, ``contract``) and the difflib backend. The
comparisons are made here, through the public API, rather than by calling
``regenerate.py``, so a drift between the two is a failure rather than a
silently regenerated golden. Accept-all and reject-all are the reference
reader's (``tests/helpers/criticmarkup.py``).
"""

from __future__ import annotations

import functools
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pytest

from redlines.alignment import AlignmentConfig
from redlines.blocks import Block
from redlines.changes import Change, ChangeKind
from redlines.comparison import Comparison, compare
from tests.helpers import criticmarkup as cm
from tests.helpers.hash_seed import assert_byte_identical_across_hash_seeds

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE = REPO_ROOT / "tests" / "corpus" / "sample_pair"
RENDERED = SAMPLE / "expected" / "rendered"
DIFFLIB = AlignmentConfig(similarity="difflib")


@dataclass(frozen=True)
class Twin:
    """One twin of the pair, and the golden its annotated view is frozen in."""

    name: str
    extension: str
    format: str
    profile: str
    golden: str


MARKDOWN = Twin("markdown", "md", "markdown", "markdown", "annotated.markdown.md")
TEXT = Twin("text", "txt", "text", "contract", "annotated.contract.txt")
TWINS = [pytest.param(MARKDOWN, id="markdown"), pytest.param(TEXT, id="text")]


def document(twin: Twin, side: str) -> str:
    return (SAMPLE / f"{side}.{twin.extension}").read_text(encoding="utf-8")


@functools.cache
def compared(twin: Twin, source: str = "source", test: str = "test") -> Comparison:
    return compare(
        document(twin, source),
        document(twin, test),
        format=twin.format,
        profile=twin.profile,
        alignment=DIFFLIB,
    )


def annotated(twin: Twin) -> str:
    return compared(twin).output_annotated()


def lines(twin: Twin) -> list[str]:
    """The view's physical lines; a table is one block of several."""
    return annotated(twin).split("\n")


def blocks(twin: Twin) -> list[str]:
    """The view's blocks, which a blank line separates."""
    return annotated(twin).split("\n\n")


def marks(text: str) -> list[cm.Token]:
    """Every mark and note the reader finds in ``text``."""
    return [token for token in cm.parse(text) if token.kind != "text"]


def the_line(twin: Twin, needle: str) -> str:
    """The one line of the view that contains ``needle``."""
    found = [line for line in lines(twin) if needle in line]
    assert len(found) == 1, (needle, found)
    return found[0]


def heading(twin: Twin, text: str) -> str:
    return ("## " if twin is MARKDOWN else "") + text


# --- P1 to P6 -------------------------------------------------------------------------


@pytest.mark.parametrize("twin", TWINS)
def test_p1_accept_all_equals_the_test_rendering_line_for_line(twin: Twin) -> None:
    test_rendering = compared(twin, "test", "test").output_annotated()
    assert cm.exact(cm.accept_all(annotated(twin)), cm.accept_all(test_rendering))


@pytest.mark.parametrize("twin", TWINS)
def test_p2_reject_all_equals_the_source_rendering_as_a_strict_multiset(
    twin: Twin,
) -> None:
    source_rendering = compared(twin, "source", "source").output_annotated()
    assert cm.multiset(cm.reject_all(annotated(twin)), cm.reject_all(source_rendering))


def _bare_reject(text: str) -> Counter[str]:
    """Reject-all without the residue rule: lines stripped, blank separators dropped."""
    return Counter(line.strip() for line in cm.lines(text, "reject") if line.strip())


def test_p2_without_the_residue_rule_only_the_markdown_row_is_left_over() -> None:
    for twin in (MARKDOWN, TEXT):
        rejected = _bare_reject(annotated(twin))
        source = _bare_reject(compared(twin, "source", "source").output_annotated())
        assert source - rejected == Counter()
        leftover = rejected - source
        assert leftover == (
            Counter({"|  |  |  |": 1}) if twin is MARKDOWN else Counter()
        ), twin


@pytest.mark.parametrize("twin", TWINS)
def test_p3_exactly_eleven_lines_carry_a_mark_the_ten_nodes_and_one_tombstone(
    twin: Twin,
) -> None:
    carrying = [line for line in lines(twin) if marks(line)]
    assert len(carrying) == 11
    tombstones = [
        line for line in carrying if line.startswith("{>>") and line.endswith("<<}")
    ]
    assert tombstones == ["{>>7.5 moved to 9.6 /section[1]/section[9]/list_item[6]<<}"]
    drawn = [line for line in carrying if line not in tombstones]
    nodes = list(compared(twin).changes)
    assert len(nodes) == len(drawn) == 10
    test_blocks = {block.path: block for block in compared(twin).test.walk()}
    drawing: list[str] = []
    for node in nodes:
        side: cm.Side = "reject" if node.kind is ChangeKind.DELETE else "accept"
        text = _drawn_text(node, test_blocks)
        hits = [line for line in drawn if text in "\n".join(cm.lines(line, side))]
        assert len(hits) == 1, (
            node.kind,
            node.test_address or node.source_address,
            hits,
        )
        drawing.extend(hits)
    assert sorted(drawing) == sorted(drawn)


def _drawn_text(node: Change, test_blocks: dict[str, Block]) -> str:
    """What a node's line says on its own side; a row says it in its cells."""
    text = node.source_text if node.kind is ChangeKind.DELETE else node.test_text
    if text:
        return text
    assert node.test_address is not None
    return " | ".join(cell.text for cell in test_blocks[node.test_address].children)


CLAUSE_11_5 = (
    "11.5 A notice given under this Agreement must be in writing and sent to the address of "
    "the receiving party set out above, or to any other address that the party notifies to the "
    "other in writing."
)


@pytest.mark.parametrize("twin", TWINS)
def test_p4_clause_11_5_appears_once_on_one_line_unmarked(twin: Twin) -> None:
    line = the_line(twin, "11.5")
    assert marks(line) == []
    assert cm.strip_roles(line) == CLAUSE_11_5
    assert line == "[clause] " + CLAUSE_11_5


def _schedule_2_items(rendered: list[str], title: str) -> list[str]:
    at = next(
        index for index, block in enumerate(rendered) if cm.strip_roles(block) == title
    )
    return rendered[at + 1 :]


@pytest.mark.parametrize("twin", TWINS)
def test_p5_in_schedule_2_exactly_one_of_the_eight_items_carries_marks(
    twin: Twin,
) -> None:
    title = ("# " if twin is MARKDOWN else "") + "Schedule 2. Service Levels"
    items = _schedule_2_items(blocks(twin), title)
    assert len(items) == 8
    assert [number for number, item in enumerate(items, 1) if marks(item)] == [3]
    written = _schedule_2_items(
        [line for line in document(twin, "test").split("\n") if line.strip()], title
    )
    assert len(written) == 8
    for number, (item, line) in enumerate(zip(items, written), 1):
        if number != 3:
            assert cm.strip_roles(item) == line, number


@pytest.mark.parametrize("side", ["source", "test"])
@pytest.mark.parametrize("twin", TWINS)
def test_p6_a_document_compared_with_itself_carries_no_mark(
    twin: Twin, side: str
) -> None:
    same = compared(twin, side, side)
    assert list(same.changes) == []
    assert marks(same.output_annotated()) == []


def test_p6_every_output_is_byte_identical_across_hash_seeds() -> None:
    script = """
import json
import sys
from pathlib import Path
from redlines.alignment import AlignmentConfig
from redlines.comparison import compare
sample = Path("tests/corpus/sample_pair")
outputs = {}
for extension, format, profile in (("md", "markdown", "markdown"), ("txt", "text", "contract")):
    def read(side):
        return (sample / f"{side}.{extension}").read_text(encoding="utf-8")
    def compared(source, test):
        return compare(read(source), read(test), format=format, profile=profile,
                       alignment=AlignmentConfig(similarity="difflib"))
    comparison = compared("source", "test")
    outputs[profile] = comparison.output_annotated()
    outputs[profile + "/no_roles"] = comparison.output_annotated(roles=False)
    for syntax in ("markdown", "text"):
        outputs[profile + "/" + syntax] = comparison.output_annotated(syntax=syntax)
    for side in ("source", "test"):
        outputs[profile + "/" + side] = compared(side, side).output_annotated()
sys.stdout.write(json.dumps(outputs))
"""
    outputs = json.loads(assert_byte_identical_across_hash_seeds(script, cwd=REPO_ROOT))
    assert len(outputs) == 12
    for twin in (MARKDOWN, TEXT):
        with open(RENDERED / twin.golden, encoding="utf-8", newline="") as handle:
            assert outputs[twin.profile] == handle.read()


# --- rows 1 to 8: the eight changes of PRD § 3a ---------------------------------------


@pytest.mark.parametrize("twin", TWINS)
def test_row_1_the_2_4_definition_carries_one_insertion_and_no_other_mark(
    twin: Twin,
) -> None:
    line = the_line(twin, '2.4 "Confidential Information"')
    assert line.endswith(
        " marked as {++confidential, or that the receiving party ought reasonably to treat "
        "as ++}confidential."
    )
    assert marks(line) == [
        cm.Token(
            "insert",
            "confidential, or that the receiving party ought reasonably to treat as ",
        )
    ]


DESTINATION = (
    "[clause] {~~7.5~>9.6~~} Each party shall return or destroy the other party's Confidential "
    "Information within ten Business Days of a written request. "
    "{>>moved from 7.5 /section[1]/section[7]/list_item[5]<<}"
)
BODY = "The obligations in this clause continue for {~~three~>five~~} years after the end of the Term."
TOMBSTONE = "{>>7.5 moved to 9.6 /section[1]/section[9]/list_item[6]<<}"


@pytest.mark.parametrize("twin", TWINS)
def test_row_2_clause_7_5_is_drawn_at_9_6_with_its_edit_and_a_tombstone_after_7_4(
    twin: Twin,
) -> None:
    drawn = blocks(twin)
    assert drawn.count(DESTINATION) == 1
    at = drawn.index(DESTINATION)
    assert cm.strip_roles(drawn[at - 1]).startswith("9.5 Termination does not affect")
    assert drawn[at + 1] == BODY
    assert drawn[at + 2] == heading(twin, "10. Liability")
    assert drawn.count(TOMBSTONE) == 1
    assert cm.strip_roles(drawn[drawn.index(TOMBSTONE) - 1]).startswith(
        "7.4 Neither party"
    )
    # No unmarked 7.5 anywhere: the label is only in the substitution and the
    # two notes, so accepting every mark leaves none.
    view = annotated(twin)
    assert not any(
        "7.5" in token.text for token in cm.parse(view) if token.kind == "text"
    )
    assert not any("7.5" in line for line in cm.lines(view, "accept"))


@pytest.mark.parametrize("twin", TWINS)
def test_row_3_the_inserted_3_3_and_the_two_renumbers_it_causes(twin: Twin) -> None:
    drawn = blocks(twin)
    at = next(
        index
        for index, block in enumerate(drawn)
        if block.startswith("[clause] {++3.3 The Supplier may engage ")
    )
    assert drawn[at].endswith("++}")
    assert drawn[at + 1].startswith("[clause] {~~3.3~>3.4~~} The Supplier shall meet ")
    assert drawn[at + 2].startswith("[clause] {~~3.4~>3.5~~} The Supplier may change ")
    assert [len(marks(block)) for block in drawn[at : at + 3]] == [1, 1, 1]


@pytest.mark.parametrize("twin", TWINS)
def test_row_4_the_cross_reference_follows_the_renumbering(twin: Twin) -> None:
    line = the_line(twin, "contrary to clause")
    assert line.endswith(" contrary to clause {~~3.3.~>3.4.~~}")
    assert marks(line) == [cm.Token("substitution", "3.3.", "3.4.")]


@pytest.mark.parametrize("twin", TWINS)
def test_row_5_the_deleted_sub_clause_c_stands_between_b_and_5_5(twin: Twin) -> None:
    drawn = blocks(twin)
    at = drawn.index(
        "[sub_clause] {--(c) The Client pays the undisputed part of the invoice on the due date.--}"
    )
    assert (
        drawn[at - 1]
        == "[sub_clause] (b) The notice states the amount in dispute and the reason for it."
    )
    assert drawn[at + 1].startswith("[clause] 5.5 Interest runs")


def test_row_6_markdown_the_inserted_row_sits_between_test_report_and_go_live() -> None:
    row = "| {++Training day++} | {++Week 9++} | {++Client++} |"
    table = lines(MARKDOWN)
    at = table.index(row)
    assert table[at - 1] == "| Test report | Week 8 | Supplier |"
    assert table[at + 1] == "| Go-live sign-off | Week 10 | Client |"
    assert lines(MARKDOWN).count(row) == 1


def test_row_6_text_the_inserted_deliverable_is_one_inserted_paragraph() -> None:
    drawn = blocks(TEXT)
    at = drawn.index(
        "[schedule] {++The training day is due by Week 9 and is owned by the Client.++}"
    )
    assert (
        drawn[at - 1]
        == "[schedule] The test report is due by Week 8 and is owned by the Supplier."
    )
    assert (
        drawn[at + 1]
        == "[schedule] The go-live sign-off is due by Week 10 and is owned by the Client."
    )


@pytest.mark.parametrize("twin", TWINS)
def test_row_7_the_rewrapped_clause_11_5_is_no_change(twin: Twin) -> None:
    address = "/section[1]/section[11]/list_item[5]"
    assert not any(
        address in (change.source_address or "", change.test_address or "")
        for change in compared(twin).changes
    )
    test_p4_clause_11_5_appears_once_on_one_line_unmarked(twin)


ROW_8 = (
    "The Supplier shall acknowledge a priority 3 incident within {~~four~>two~~} hours and shall "
    "restore the Services within {~~two~>one~~} Business {~~Days.~>Day.~~}"
)


@pytest.mark.parametrize("twin", TWINS)
def test_row_8_the_repetitive_schedule_marks_item_3_and_nothing_else(
    twin: Twin,
) -> None:
    prefix = "3. [schedule] " if twin is MARKDOWN else "[schedule] 3. "
    assert lines(twin).count(prefix + ROW_8) == 1
    assert [token.kind for token in marks(prefix + ROW_8)] == ["substitution"] * 3


# --- the goldens ----------------------------------------------------------------------


@pytest.mark.parametrize("twin", TWINS)
def test_the_golden_is_output_annotated_byte_for_byte(twin: Twin) -> None:
    with open(RENDERED / twin.golden, encoding="utf-8", newline="") as handle:
        golden = handle.read()
    assert annotated(twin) == golden, (
        f"tests/corpus/sample_pair/expected/rendered/{twin.golden} no longer matches "
        "output_annotated(). If the change is intentional, regenerate with: "
        "uv run python tests/corpus/sample_pair/regenerate.py --rendered, and have houfu "
        "read the new golden"
    )
