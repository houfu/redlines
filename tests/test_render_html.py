"""The HTML renderer and the MCP App fragment (#182, ADR-0038).

`redlines.comparison.Comparison.output_html` (the change list) and
``output_annotated(syntax="html")`` (the document view) are the only producers
of change HTML in the project, and the MCP App shell and the documentation
site inject them as they are. So this module holds them to the fragment
contract with the checks F1 to F9 of ``tests/helpers/fragment_checks.py``, a
reader written from the ADR, on:

- the seven fixtures, the sample pair's two twins and the five renderer
  cases, whose goldens are checked byte for byte;
- the 60 committed runs;
- a hostile corpus: the committed ``hostile`` case, markdown and text pairs
  carrying every attack F7 names, and a comparison built from block trees,
  so that labels, roles, headings, cells, a reader's drop report and a
  filter's values are hostile too.

Then the claims around the contract: what the document view draws (headings,
ghosts, moves, renumbers, tables, roles), filtered comparisons, the API's
``syntax`` handling, the size of the change list on the sample pair, and
determinism across hash seeds.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import pytest

from redlines.alignment import AlignmentConfig
from redlines.blocks import Block, BlockKind, BlockTree, Dropped
from redlines.comparison import SCHEMA_VERSION, Comparison, compare
from redlines.renderers import FRAGMENT_VERSION, STYLESHEET
from redlines.renderers._html import THEME, render_change_list, render_document
from tests.helpers import fragment_checks as fc
from tests.helpers.committed_runs import CommittedRun, committed_runs
from tests.helpers.hash_seed import assert_byte_identical_across_hash_seeds

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE = REPO_ROOT / "tests" / "corpus" / "sample_pair"
RENDERED = SAMPLE / "expected" / "rendered"
CASES = REPO_ROOT / "tests" / "renderer_cases"
CASE_NAMES = ("four_kinds", "moved_neighbour", "nested_move", "trailing_insert", "hostile")
DIFFLIB = AlignmentConfig(similarity="difflib")

# (fixture, change-list golden, document-view golden)
GOLDENS: tuple[tuple[str, Path, Path], ...] = (
    ("sample_pair.md", RENDERED / "changes.markdown.html", RENDERED / "annotated.markdown.html"),
    ("sample_pair.txt", RENDERED / "changes.contract.html", RENDERED / "annotated.contract.html"),
    *(
        (name, CASES / name / "changes.html", CASES / name / "annotated.html")
        for name in CASE_NAMES
    ),
)
FIXTURES: tuple[str, ...] = tuple(name for name, _, _ in GOLDENS)


def _read(path: Path) -> str:
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


@lru_cache(maxsize=None)
def fixture(name: str) -> Comparison:
    """A fixture compared the way its goldens were generated: named format and profile, difflib."""
    if name.startswith("sample_pair."):
        extension = name.removeprefix("sample_pair.")
        fmt, profile = ("markdown", "markdown") if extension == "md" else ("text", "contract")
        return compare(
            _read(SAMPLE / f"source.{extension}"),
            _read(SAMPLE / f"test.{extension}"),
            format=fmt,
            profile=profile,
            alignment=DIFFLIB,
        )
    return compare(
        _read(CASES / name / "source.md"),
        _read(CASES / name / "test.md"),
        format="markdown",
        profile="markdown",
        alignment=DIFFLIB,
    )


def changes_of(comparison: Comparison) -> str:
    return comparison.output_html()


def document_of(comparison: Comparison) -> str:
    return comparison.output_annotated(syntax="html")


def check_both(comparison: Comparison) -> tuple[fc.Element, fc.Element]:
    """F1 to F9 on both fragments of one comparison, the document view with and without roles."""
    changes = fc.check_deterministic(changes_of, comparison)
    root = fc.check_change_list(changes, comparison)
    fc.check_filter_parity(root, comparison)
    document = fc.check_deterministic(document_of, comparison)
    for roles in (True, False):
        fc.check_document(
            comparison.output_annotated(syntax="html", roles=roles), comparison, roles=roles
        )
    return root, fc.check_well_formed(document)


# --- the goldens ------------------------------------------------------------------


@pytest.mark.parametrize(("name", "changes", "annotated"), GOLDENS, ids=FIXTURES)
def test_both_fragments_match_their_goldens_byte_for_byte(
    name: str, changes: Path, annotated: Path
) -> None:
    comparison = fixture(name)
    assert comparison.output_html() == _read(changes)
    assert comparison.output_annotated(syntax="html") == _read(annotated)


def test_the_goldens_are_generated_under_difflib_with_the_profile_named() -> None:
    for name in FIXTURES:
        config = fixture(name).config
        assert config.similarity == "difflib"
        assert config.profile in ("markdown", "contract")


# --- F1 to F9 on every fixture ----------------------------------------------------


@pytest.mark.parametrize("name", FIXTURES)
def test_both_fragments_of_every_fixture_pass_f1_to_f9(name: str) -> None:
    check_both(fixture(name))


RUNS: tuple[CommittedRun, ...] = committed_runs()


@pytest.mark.parametrize("run", RUNS, ids=[f"{run.name}@{run.format}" for run in RUNS])
def test_both_fragments_of_every_committed_run_pass_f1_to_f9(run: CommittedRun) -> None:
    source, test = run.texts()
    check_both(compare(source, test, format=run.format))


# --- the hostile corpus (F7) ----------------------------------------------------------

ATTACKS: tuple[str, ...] = (
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    '"><script>alert(1)</script>',
    "</style>",
    "\"double\", 'single' & ampersand &amp;",
    "{++x++} and ~> and {>>note<<}",
    "a backslash before a brace \\{--y--}",
    "bidi \u202edesrever\u202c and \u2066isolated\u2069",
)
HOSTILE = " ".join(ATTACKS)

HOSTILE_MARKDOWN = (
    f"## 1. Attacks {ATTACKS[3]} & <b>\n\n"
    f"1.1 Kept: {HOSTILE} ends C:\\dir\\old\n\n"
    f"1.2 Struck out entirely: {ATTACKS[0]} {ATTACKS[3]} {ATTACKS[4]}\n\n"
    "| Cell | Note |\n| --- | --- |\n"
    f"| {ATTACKS[1]} | ~> |\n| gone {ATTACKS[3]} | \\| piped |\n",
    f"## 1. Attacks {ATTACKS[3]} & <b>\n\n"
    f"1.1 Kept: {HOSTILE} ends C:\\dir\\new\n\n"
    f"1.3 A brand new obligation: {ATTACKS[2]} {ATTACKS[5]} {ATTACKS[6]}\n\n"
    "| Cell | Note |\n| --- | --- |\n"
    f"| {ATTACKS[1]} | ~> changed |\n| new {ATTACKS[7]} | {{++z++}} |\n",
)

HOSTILE_TEXT = (
    f"1. Attacks {ATTACKS[3]}\n\n1.1 Kept: {HOSTILE} ends C:\\dir\\old\n\n"
    f"1.2 Struck out entirely: {ATTACKS[0]} {ATTACKS[3]} {ATTACKS[4]}\n",
    f"1. Attacks {ATTACKS[3]}\n\n1.1 Kept: {HOSTILE} ends C:\\dir\\new\n\n"
    f"1.3 A brand new obligation: {ATTACKS[2]} {ATTACKS[5]} {ATTACKS[6]} {ATTACKS[7]}\n",
)

HOSTILE_ROLE = '"><script>alert(1)</script>'
HOSTILE_LABEL = '1"><img src=x onerror=alert(1)>'


def _tree(*children: Block, dropped: tuple[Dropped, ...] = ()) -> BlockTree:
    return BlockTree.build(Block(kind=BlockKind.DOCUMENT, children=children), dropped=dropped)


def _section(heading: str, *children: Block) -> Block:
    return Block(
        kind=BlockKind.SECTION,
        children=(
            Block(
                kind=BlockKind.HEADING,
                text=heading,
                label=HOSTILE_LABEL,
                level=1,
                attrs={"label_raw": HOSTILE_LABEL + ".", "atx_level": 99},
            ),
            *children,
        ),
    )


def _table(*rows: tuple[str, ...]) -> Block:
    return Block(
        kind=BlockKind.TABLE,
        children=tuple(
            Block(kind=BlockKind.ROW, children=tuple(Block(kind=BlockKind.CELL, text=cell) for cell in row))
            for row in rows
        ),
    )


def _clause(label: str, text: str, role: str | None = None) -> Block:
    return Block(kind=BlockKind.PARAGRAPH, text=text, label=label, level=2, role=role)


@lru_cache(maxsize=None)
def hostile_trees() -> Comparison:
    """Hostile strings everywhere a reader, a profile or the engine can put one."""
    source = _tree(
        _section(
            f"Heading {HOSTILE}",
            _clause("(a)", f"Kept {HOSTILE} and C:\\dir\\old", HOSTILE_ROLE),
            _clause("(b)", f"Struck out entirely: {ATTACKS[0]} {ATTACKS[3]}", "x</style>y"),
            _clause('(c)"', f"Moved away {HOSTILE}"),
            _table(("Item", "Note"), (HOSTILE, "a | b"), ("gone", "</style>")),
        ),
        _section("Second </style>", _clause("(d)", "Another clause stays as it is.")),
        dropped=(
            Dropped(kind="<img src=x onerror=alert(1)>", count=2, reason='"><script>alert(1)</script> & </style>'),
        ),
    )
    test = _tree(
        _section(
            f"Heading {HOSTILE}",
            _clause("(a)", f"Kept {HOSTILE} and C:\\dir\\new", HOSTILE_ROLE),
            _table(("Item", "Note"), (HOSTILE, "a | b"), ("new </style>", "{++x++}")),
            _clause("(e)", f"A brand new obligation: {ATTACKS[1]} {ATTACKS[2]} {ATTACKS[5]}", HOSTILE_ROLE),
        ),
        _section(
            "Second </style>",
            _clause("(d)", "Another clause stays as it is."),
            _clause('(f)"><b>', f"Moved away {HOSTILE}"),
        ),
        dropped=(Dropped(kind="</style>", count=1, reason="<script>alert(1)</script>"),),
    )
    return compare(source, test, alignment=DIFFLIB)


def hostile_comparisons() -> dict[str, Comparison]:
    trees = hostile_trees()
    return {
        "markdown": compare(*HOSTILE_MARKDOWN, format="markdown", alignment=DIFFLIB),
        "text": compare(*HOSTILE_TEXT, format="text", alignment=DIFFLIB),
        "trees": trees,
        "trees, filtered": trees.filter(labels=(HOSTILE_ROLE, "(a)", "(e)"), roles=(HOSTILE_ROLE,)),
        "committed case": fixture("hostile"),
    }


@pytest.mark.parametrize("name", list(hostile_comparisons()))
def test_hostile_input_passes_f1_to_f9_and_reads_back_exactly(name: str) -> None:
    comparison = hostile_comparisons()[name]
    check_both(comparison)
    for fragment in (comparison.output_html(), comparison.output_annotated(syntax="html")):
        after_the_stylesheet = fragment.split("</style>", 1)[1]
        for raw in ("<script", "<img", "</style>", "<b>", " onerror"):
            assert raw not in after_the_stylesheet.replace("&lt;img src=x onerror", ""), (name, raw)


def test_the_hostile_corpus_has_every_kind_and_every_attack() -> None:
    trees = hostile_trees()
    assert {change.kind.value for change in trees.changes} == {"insert", "delete", "modify", "move"}
    markdown = hostile_comparisons()["markdown"]
    assert {change.kind.value for change in markdown.changes} >= {"insert", "delete", "modify"}
    fragment = trees.output_html()
    after_the_stylesheet = fragment.split("</style>", 1)[1]
    for attack in ATTACKS:
        if any(character in attack for character in "<>&"):
            assert attack not in after_the_stylesheet, attack
    root = fc.parse(fragment)
    shown = root.text()
    for attack in ATTACKS[:4]:
        assert attack in shown  # every attack reaches the reader as text, escaped
    assert any(element.get("data-role") == HOSTILE_ROLE for element in root.walk())
    assert any(element.get("data-test-label") == '(f)"><b>' for element in root.walk())
    notices = [element.text() for element in root.walk() if "redlines-notice" in element.classes()]
    assert notices == [
        "2 <img src=x onerror=alert(1)> dropped from the source: "
        '"><script>alert(1)</script> & </style>',
        "1 </style> dropped from the test: <script>alert(1)</script>",
    ]


def test_a_hostile_filter_value_is_escaped_in_its_notice() -> None:
    filtered = hostile_comparisons()["trees, filtered"]
    root = fc.parse(filtered.output_html())
    (notice,) = [element for element in root.walk() if element.get("data-notice") == "filtered"]
    assert notice.text() == f"Filtered: labels={HOSTILE_ROLE},(a),(e); roles={HOSTILE_ROLE}"


def test_a_hostile_heading_level_is_clamped() -> None:
    root = fc.parse(hostile_trees().output_annotated(syntax="html"))
    headings = [element for element in root.walk() if element.get("role") == "heading"]
    assert headings and {element.get("aria-level") for element in headings} == {"6"}


# --- the document view ---------------------------------------------------------------


def _document(comparison: Comparison, *, roles: bool = True) -> list[fc.Element]:
    root = fc.parse(comparison.output_annotated(syntax="html", roles=roles))
    (document,) = [element for element in root.walk() if "redlines-document" in element.classes()]
    return document.elements()


def _heading(level: int, atx: object) -> int:
    attrs = {} if atx is None else {"atx_level": atx}
    tree = _tree(Block(kind=BlockKind.HEADING, text="Title", level=level, attrs=attrs))
    (element,) = _document(compare(tree, tree))
    assert element.get("role") == "heading"
    return int(element.get("aria-level") or "0")


@pytest.mark.parametrize(
    ("level", "atx", "expected"),
    [(1, 2, 2), (1, None, 2), (0, None, 1), (5, None, 6), (9, None, 6), (1, 99, 6), (1, 0, 1),
     (1, -3, 1), (3, "4", 4), (3, "x", 4), (3, True, 4)],
)
def test_a_heading_is_role_heading_with_a_clamped_aria_level(level: int, atx: object, expected: int) -> None:
    assert _heading(level, atx) == expected


def test_the_document_view_has_no_h1_to_h6_and_no_id() -> None:
    for name in FIXTURES:
        fragment = fixture(name).output_annotated(syntax="html")
        assert not re.search(r"<h[1-6][\s>]", fragment), name
        assert " id=" not in fragment


def test_a_ghost_carries_no_test_address_and_a_tombstone_names_both_ends() -> None:
    elements = _document(fixture("four_kinds"))
    (ghost,) = [element for element in elements if element.get("data-kind") == "delete"]
    assert ghost.names() == ["class", "data-source-address", "data-level", "data-kind", "data-role"]
    assert ghost.get("data-source-address") == "/section[2]/list_item[2]"
    (tombstone,) = [element for element in elements if "redlines-note" in element.classes()]
    assert tombstone.attrs == [
        ("class", "redlines-note"),
        ("data-kind", "move"),
        ("data-source-address", "/section[1]/list_item[2]"),
        ("data-test-address", "/section[2]/list_item[2]"),
    ]
    assert tombstone.text() == "1.2 moved to 2.2 /section[2]/list_item[2]"
    (moved,) = [element for element in elements if element.get("data-kind") == "move"
                and "redlines-block" in element.classes()]
    notes = [child for child in moved.elements() if "redlines-note" in child.classes()]
    assert [note.text() for note in notes] == ["moved from 1.2 /section[1]/list_item[2]"]
    assert moved.elements()[-1] is notes[0]
    assert moved.get("data-source-address") == "/section[1]/list_item[2]"


def test_a_renumber_is_a_label_span_of_a_delete_and_an_insert() -> None:
    elements = _document(fixture("sample_pair.md"))
    renumbered = [element for element in elements if element.get("data-kind") == "renumber"]
    assert len(renumbered) == 2
    label = renumbered[0].elements()[1]
    assert label.attrs == [("class", "redlines-label")]
    assert [(mark.tag, mark.text()) for mark in label.elements()] == [("del", "3.3"), ("ins", "3.4")]


def test_an_inserted_block_wraps_its_label_and_text_in_one_ins() -> None:
    elements = _document(fixture("four_kinds"))
    (inserted,) = [element for element in elements if element.get("data-kind") == "insert"]
    role, mark = inserted.elements()
    assert role.classes() == ["redlines-role"] and mark.tag == "ins"
    assert mark.elements()[0].classes() == ["redlines-label"]
    assert mark.text() == "1.2 The Buyer may reject goods that do not match the order."


def _table_document(test: str) -> fc.Element:
    source = (
        "## Deliverables\n\n| Item | Owner |\n| --- | --- |\n"
        "| Plan | Supplier |\n| Report | Supplier |\n| Review | Client |\n"
    )
    comparison = compare(source, test, format="markdown", alignment=DIFFLIB)
    check_both(comparison)
    (table,) = [element for element in _document(comparison) if element.tag == "table"]
    return table


def _rows(table: fc.Element) -> list[list[str]]:
    return [
        [f"{cell.tag}:{cell.text()}" + ("-" if cell.elements() and cell.elements()[0].tag == "del" else "")
         for cell in row.elements()]
        for part in table.elements()
        for row in part.elements()
    ]


def test_a_table_places_a_deleted_row_where_it_stood() -> None:
    table = _table_document(
        "## Deliverables\n\n| Item | Owner |\n| --- | --- |\n| Plan | Supplier |\n| Review | Client |\n"
    )
    assert _rows(table) == [
        ["th:Item", "th:Owner"],
        ["td:Plan", "td:Supplier"],
        ["td:Report-", "td:Supplier-"],
        ["td:Review", "td:Client"],
    ]


def test_a_deleted_first_row_never_becomes_the_header() -> None:
    table = _table_document(
        "## Deliverables\n\n| Item | Owner |\n| --- | --- |\n| Report | Supplier |\n| Review | Client |\n"
    )
    assert _rows(table)[:2] == [["th:Item", "th:Owner"], ["td:Plan-", "td:Supplier-"]]


def test_a_cell_pipe_is_written_as_a_pipe() -> None:
    elements = _document(fixture("hostile"))
    (table,) = [element for element in elements if element.tag == "table"]
    assert "a | b" in [cell.text() for cell in table.walk() if cell.tag == "td"]


def test_roles_false_drops_the_role_spans_and_keeps_data_role() -> None:
    with_roles = _document(fixture("four_kinds"))
    without = _document(fixture("four_kinds"), roles=False)
    assert any("redlines-role" in element.classes() for block in with_roles for element in block.walk())
    assert not any("redlines-role" in element.classes() for block in without for element in block.walk())
    assert [block.get("data-role") for block in with_roles] == [block.get("data-role") for block in without]
    assert without[1].text() == (
        "1.1 The Supplier shall deliver the goods within thirty (30sixty (60) days of each order."
    )


# --- the change list --------------------------------------------------------------


def test_a_move_row_shows_both_labels_both_addresses_and_the_label_change() -> None:
    root = fc.parse(fixture("four_kinds").output_html())
    (row,) = [row for row in fc.row_elements(root) if row.get("data-kind") == "move"]
    summary, body = row.elements()[0].elements()
    texts = {span.classes()[0]: span.text() for span in summary.elements()}
    assert texts["redlines-label"] == "1.2 → 2.2"
    assert texts["redlines-address"] == "/section[1]/list_item[2] → /section[2]/list_item[2]"
    assert body.elements()[0].classes() == ["redlines-label"]
    assert [(mark.tag, mark.text()) for mark in body.elements()[0].elements()] == [("del", "1.2"), ("ins", "2.2")]


def test_an_inserted_row_shows_its_cells_joined() -> None:
    root = fc.parse(fixture("sample_pair.md").output_html())
    (row,) = [row for row in fc.row_elements(root) if row.get("data-block-kind") == "row"]
    summary, body = row.elements()[0].elements()
    assert {span.classes()[0]: span.text() for span in summary.elements()}["redlines-excerpt"] == (
        "Training day | Week 9 | Client"
    )
    assert body.text() == "Training day | Week 9 | Client"


def test_an_excerpt_is_cut_at_a_space_within_80_characters() -> None:
    long = "word " * 30
    tree_a = _tree(Block(kind=BlockKind.PARAGRAPH, text=long + "first"))
    tree_b = _tree(Block(kind=BlockKind.PARAGRAPH, text=long + "second"))
    root = fc.parse(compare(tree_a, tree_b).output_html())
    excerpt = [element for element in root.walk() if "redlines-excerpt" in element.classes()][0].text()
    assert excerpt == ("word " * 16).rstrip() + "…"
    unbroken = _tree(Block(kind=BlockKind.PARAGRAPH, text="x" * 100))
    root = fc.parse(compare(_tree(), unbroken).output_html())
    excerpt = [element for element in root.walk() if "redlines-excerpt" in element.classes()][0].text()
    assert excerpt == "x" * 80 + "…"


def test_no_changes_says_so_and_counts_none() -> None:
    comparison = fixture("four_kinds")
    same = compare(comparison.test, comparison.test)
    root = fc.check_change_list(same.output_html(), same)
    assert [element.text() for element in root.walk() if "redlines-empty" in element.classes()] == ["No changes."]
    assert "0 changes" in root.text()
    assert not any(element.get("data-kind") for element in _document(same))


def test_one_change_is_singular_and_a_dropped_report_is_a_notice() -> None:
    comparison = compare("7.1 The\x00 fee\x07 is due.", "7.1 The fee is due today.", format="text")
    root = fc.check_change_list(comparison.output_html(), comparison)
    texts = [element.text() for element in root.walk() if element.get("data-count") == "total"]
    assert texts == ["1 change"]
    (notice,) = [element for element in root.walk() if element.get("data-notice") == "dropped"]
    assert notice.get("data-side") == "source"
    assert notice.text().startswith("2 control_character dropped from the source: Control characters")


def test_an_exhausted_budget_is_a_notice() -> None:
    comparison = compare(
        "The fee is due.\n\nA second paragraph here.",
        "The fee is due now.\n\nA second paragraph, edited, here.",
        format="text",
        alignment=AlignmentConfig(similarity="difflib", max_comparisons=0),
    )
    assert comparison.config.budget_exhausted
    for fragment in (comparison.output_html(), comparison.output_annotated(syntax="html")):
        root = fc.parse(fragment)
        notices = [element.get("data-notice") for element in root.walk() if element.get("data-notice")]
        assert notices == ["budget-exhausted"]
    check_both(comparison)


# --- filtered comparisons ----------------------------------------------------------


def test_a_filtered_change_list_lists_only_its_nodes_and_says_so() -> None:
    filtered = fixture("sample_pair.md").filter(kinds=("modify",), min_chars=5)
    check_both(filtered)
    root = fc.parse(filtered.output_html())
    rows = fc.row_elements(root)
    # Four modify nodes, less 9.2's cross-reference, whose "3.3." to "3.4." is 4 characters.
    assert len(rows) == len(filtered.changes) == 3
    assert [row.get("data-index") for row in rows] == ["0", "1", "2"]
    assert "/section[1]/section[9]/list_item[2]" not in [row.get("data-address") for row in rows]
    assert {row.get("data-kind") for row in rows} == {"modify"}
    (notice,) = [element for element in root.walk() if element.get("data-notice") == "filtered"]
    assert notice.text() == "Filtered: kinds=modify; min_chars=5"


def test_a_filtered_document_view_marks_only_its_own_nodes() -> None:
    full = fixture("four_kinds")
    filtered = full.filter(kinds=("modify",))
    marked = [element.get("data-kind") for element in _document(filtered) if element.get("data-kind")]
    assert marked == ["modify"]
    inserted = [element for element in _document(filtered) if "The Buyer may reject" in element.text()]
    assert inserted and not inserted[0].get("data-kind")
    assert "<ins>" not in "".join(
        str(child) for element in inserted for child in element.children if isinstance(child, str)
    )


def test_a_filter_with_no_constraint_writes_no_notice() -> None:
    comparison = fixture("four_kinds").filter()
    root = fc.check_change_list(comparison.output_html(), comparison)
    assert not [element for element in root.walk() if element.get("data-notice")]


# --- the API ------------------------------------------------------------------------


def test_the_methods_are_the_renderers_with_the_schema_version() -> None:
    comparison = fixture("four_kinds")
    assert comparison.output_html() == render_change_list(comparison, schema_version=SCHEMA_VERSION)
    assert comparison.output_annotated(syntax="html") == render_document(
        comparison, schema_version=SCHEMA_VERSION, roles=True
    )
    assert comparison.output_annotated(syntax="html", roles=False) == render_document(
        comparison, schema_version=SCHEMA_VERSION, roles=False
    )


@pytest.mark.parametrize("syntax", ["HTML", "Html", "xml", "", "md", " html"])
def test_an_unknown_syntax_raises(syntax: str) -> None:
    with pytest.raises(ValueError, match="None, 'text', 'markdown' or 'html'"):
        fixture("four_kinds").output_annotated(syntax=syntax)  # type: ignore[arg-type]


def test_no_syntax_never_means_html() -> None:
    for name in ("four_kinds", "sample_pair.txt"):
        rendered = fixture(name).output_annotated()
        assert not rendered.startswith("<section")
        expected = "markdown" if name == "four_kinds" else "text"
        assert rendered == fixture(name).output_annotated(syntax=expected)  # type: ignore[arg-type]


def test_the_package_exports_the_version_and_the_stylesheet() -> None:
    import redlines.renderers

    assert redlines.renderers.__all__ == ("FRAGMENT_VERSION", "STYLESHEET")
    assert FRAGMENT_VERSION == "1.0"
    for name in FIXTURES[:2]:
        for fragment in (fixture(name).output_html(), fixture(name).output_annotated(syntax="html")):
            assert fragment.count(f"<style>{STYLESHEET}</style>") == 1
            assert f'data-redlines-fragment="{FRAGMENT_VERSION}"' in fragment


def test_the_theme_table_is_the_adrs() -> None:
    assert {name: standard or None for name, standard, _ in THEME} == fc.STANDARD_VARIABLES
    assert fc.check_theme(STYLESHEET) == set(fc.STANDARD_VARIABLES)
    fc.check_scoped(STYLESHEET)
    assert "color-scheme" not in STYLESHEET and "@" not in STYLESHEET


# --- size --------------------------------------------------------------------------


def test_the_change_list_costs_a_fixed_part_and_about_a_kilobyte_per_node() -> None:
    """ADR-0038 measured about 2 KB fixed and 1.05 KB per node on a prototype.

    The per-node cost holds (about 1.07 KB). The fixed part is about 5.1 KB,
    4.2 KB of it the stylesheet: the amended theming reads every colour
    through the standard variables, every selector is scoped under
    ``.redlines``, and one stylesheet serves both views, where the
    prototype's 1,862 bytes styled the change list alone. The bounds are
    loose on purpose; the golden holds the exact bytes.
    """
    comparison = fixture("sample_pair.md")
    full = len(comparison.output_html().encode("utf-8"))
    empty = len(comparison.filter(min_chars=1_000_000).output_html().encode("utf-8"))
    per_node = (full - empty) / len(comparison.changes)
    assert len(STYLESHEET.encode("utf-8")) < 5_000
    assert empty < 6_000
    assert 700 < per_node < 1_500


def test_the_document_view_grows_with_the_document() -> None:
    comparison = fixture("sample_pair.md")
    document = len(comparison.output_annotated(syntax="html").encode("utf-8"))
    test_bytes = len(_read(SAMPLE / "test.md").encode("utf-8"))
    blocks = comparison.statistics().test_blocks
    assert document < 1.1 * test_bytes + 250 * blocks + 6_000


# --- determinism across hash seeds ---------------------------------------------------


def test_both_fragments_are_byte_identical_under_every_hash_seed() -> None:
    script = """
from pathlib import Path
from redlines.alignment import AlignmentConfig
from redlines.comparison import compare

root = Path("tests/corpus/sample_pair")
config = AlignmentConfig(similarity="difflib")
for extension, fmt, profile in (("md", "markdown", "markdown"), ("txt", "text", "contract")):
    comparison = compare(
        (root / f"source.{extension}").read_text(encoding="utf-8"),
        (root / f"test.{extension}").read_text(encoding="utf-8"),
        format=fmt, profile=profile, alignment=config,
    )
    for filtered in (comparison, comparison.filter(kinds=("modify", "move"))):
        print(filtered.output_html())
        print(filtered.output_annotated(syntax="html"))
        print(filtered.output_annotated(syntax="html", roles=False))
case = Path("tests/renderer_cases/hostile")
hostile = compare((case / "source.md").read_text(encoding="utf-8"),
                  (case / "test.md").read_text(encoding="utf-8"), format="markdown", alignment=config)
print(hostile.output_html())
print(hostile.output_annotated(syntax="html"))
"""
    output = assert_byte_identical_across_hash_seeds(script, cwd=REPO_ROOT)
    assert output.count('<section class="redlines"') == 14
