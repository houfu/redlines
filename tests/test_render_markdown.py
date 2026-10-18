"""``Comparison.output_markdown``: 0.6's six styles and ``custom_css`` over the change tree (#179, ADR-0037).

A renderer over a block tree cannot be byte-identical to 0.6's token stream
(ADR-0036), so the method has goldens of its own, and three checks keep the
goldens from being their own oracle:

- houfu read the sample pair's goldens against ``CHANGES.md``, and the small
  cases' against their inputs, once; that reading froze them. Every golden is
  checked byte for byte here, one test per file, rendered by this module
  itself rather than by the script that wrote it;
- a drift test against 0.6 on the README fox pair, for every style;
- the ``none`` style's invariant on the 60 committed runs: accepting every
  mark gives the test rendering exactly, and rejecting every mark gives the
  source rendering *in source order*, up to whitespace and syntax heads,
  because the legacy styles strike a moved block where it was.

Everything goes through the public method; ``tests/test_inplace_core.py`` pins
the traversal underneath it.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from redlines import Redlines
from redlines.alignment import AlignmentConfig
from redlines.comparison import Comparison, compare
from redlines.enums import MarkdownStyle
from tests.helpers import criticmarkup as cm
from tests.helpers.committed_runs import COMMITTED_RUN_COUNT, committed_runs
from tests.helpers.hash_seed import assert_byte_identical_across_hash_seeds

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE = REPO_ROOT / "tests" / "corpus" / "sample_pair"
RENDERED = SAMPLE / "expected" / "rendered"
CASES = REPO_ROOT / "tests" / "renderer_cases"
QUICKSTART = REPO_ROOT / "tests" / "corpus" / "readme_quickstart"

# The goldens' backend, written out again rather than imported from the
# scripts that wrote them (tests/corpus/sample_pair/regenerate.py,
# tests/renderer_cases/regenerate.py).
GOLDEN_ALIGNMENT = AlignmentConfig(similarity="difflib")

STYLES: tuple[str, ...] = (
    "red_green",
    "none",
    "red",
    "ghfm",
    "bbcode",
    "streamlit",
    "custom_css",
)
CASE_NAMES = ("four_kinds", "moved_neighbour", "nested_move", "trailing_insert", "hostile")

# Each style's (insert, delete) delimiters, as ADR-0037's table and 0.6 spell them.
DELIMITERS: dict[str, tuple[tuple[str, str], tuple[str, str]]] = {
    "red_green": (
        ("<span style='color:green;font-weight:700;'>", "</span>"),
        ("<span style='color:red;font-weight:700;text-decoration:line-through;'>", "</span>"),
    ),
    "none": (("<ins>", "</ins>"), ("<del>", "</del>")),
    "red": (
        ("<span style='color:red;font-weight:700;'>", "</span>"),
        ("<span style='color:red;font-weight:700;text-decoration:line-through;'>", "</span>"),
    ),
    "ghfm": (("**", "**"), ("~~", "~~")),
    "bbcode": (("[b][color=green]", "[/color][/b]"), ("[s][color=red]", "[/color][/s]")),
    "streamlit": (("**:green[", "]** "), ("~~:red[", "]~~ ")),
    "custom_css": (
        ("<span class='redline-inserted'>", "</span>"),
        ("<span class='redline-deleted'>", "</span>"),
    ),
}


def read(path: Path) -> str:
    """A file's text exactly as committed: no newline translation."""
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def sample(twin: str) -> Comparison:
    """One twin of the sample pair, read as the change-tree goldens read it."""
    extension, profile = ("md", "markdown") if twin == "markdown" else ("txt", "contract")
    return compare(
        read(SAMPLE / f"source.{extension}"),
        read(SAMPLE / f"test.{extension}"),
        format=twin,
        profile=profile,
        alignment=GOLDEN_ALIGNMENT,
    )


def case(name: str, alignment: AlignmentConfig = GOLDEN_ALIGNMENT) -> Comparison:
    """One renderer case, read as markdown."""
    return compare(
        read(CASES / name / "source.md"),
        read(CASES / name / "test.md"),
        format="markdown",
        alignment=alignment,
    )


@pytest.fixture(scope="module")
def twins() -> dict[str, Comparison]:
    return {"md": sample("markdown"), "txt": sample("text")}


# --- the goldens, one test per file -------------------------------------------------------


SAMPLE_GOLDENS = [f"markdown.{style}.{extension}" for style in STYLES for extension in ("md", "txt")]
CASE_GOLDENS = [("four_kinds", style) for style in STYLES] + [
    (name, "none") for name in CASE_NAMES if name != "four_kinds"
]


@pytest.mark.parametrize("file_name", SAMPLE_GOLDENS)
def test_the_sample_pair_renders_its_golden(twins: dict[str, Comparison], file_name: str) -> None:
    """``markdown.<style>.md`` is the markdown twin as markdown; ``.txt`` the text twin as text."""
    _, style, extension = file_name.split(".")
    assert twins[extension].output_markdown(style) == read(RENDERED / file_name)


@pytest.mark.parametrize(
    ("name", "style"), CASE_GOLDENS, ids=[f"{name}/markdown.{style}.md" for name, style in CASE_GOLDENS]
)
def test_each_renderer_case_renders_its_golden(name: str, style: str) -> None:
    assert case(name).output_markdown(style) == read(CASES / name / f"markdown.{style}.md")


def _respell(none_rendering: str, style: str) -> str:
    """Rewrite the ``none`` style's tags with another style's delimiters."""
    (ins_open, ins_close), (del_open, del_close) = DELIMITERS[style]

    def spell(match: re.Match[str]) -> str:
        if match.group(1) == "ins":
            return ins_open + match.group(2) + ins_close
        return del_open + match.group(2) + del_close

    return re.sub(r"<(ins|del)>(.*?)</\1>", spell, none_rendering, flags=re.S)


@pytest.mark.parametrize("style", STYLES)
def test_every_style_is_the_none_rendering_with_its_own_delimiters(
    twins: dict[str, Comparison], style: str
) -> None:
    """The styles differ in their delimiters and nothing else, on every golden's input.

    No input here contains an ``<ins>`` or ``<del>`` of its own, so the ``none``
    rendering's tags are exactly its marks.
    """
    comparisons = [*twins.values(), *(case(name) for name in CASE_NAMES)]
    for comparison in comparisons:
        none = comparison.output_markdown("none")
        assert comparison.output_markdown(style) == _respell(none, style)


# --- the drift test against 0.6 (ADR-0036) -----------------------------------------------


@pytest.mark.parametrize("style", STYLES)
def test_the_readme_pair_renders_as_0_6_renders_it(style: str) -> None:
    source, test = read(QUICKSTART / "source.txt"), read(QUICKSTART / "test.txt")
    expected = Redlines(source, test, markdown_style=style).output_markdown
    assert compare(source, test, format="text").output_markdown(style) == expected


def test_custom_css_with_its_own_classes_renders_the_readme_pair_as_0_6_does() -> None:
    source, test = read(QUICKSTART / "source.txt"), read(QUICKSTART / "test.txt")
    expected = Redlines(
        source, test, markdown_style="custom_css", ins_class="added", del_class="removed"
    ).output_markdown
    rendered = compare(source, test, format="text").output_markdown(
        "custom_css", ins_class="added", del_class="removed"
    )
    assert rendered == expected
    assert "<span class='added'>walks past </span>" in rendered


def test_the_none_style_on_the_readme_pair_is_its_m0_golden() -> None:
    """Through the real text reader, the tree, 0.6 and the M0 golden agree byte for byte."""
    source, test = read(QUICKSTART / "source.txt"), read(QUICKSTART / "test.txt")
    rendered = compare(source, test, format="text").output_markdown("none")
    assert rendered == read(QUICKSTART / "golden" / "none.md")


# --- the none style's invariant on the 60 committed runs ----------------------------------


def _none_oracle() -> dict[str, list[str]]:
    """Which runs fail each comparison of the ``none`` style's accept and reject sides."""
    failures: dict[str, list[str]] = {"accept": [], "order_loose": [], "order_strict": []}
    runs = committed_runs()
    assert len(runs) == COMMITTED_RUN_COUNT
    for run in runs:
        source, test = run.texts()
        rendered = compare(source, test, format=run.format).output_markdown("none")
        test_rendering = compare(test, test, format=run.format).output_markdown("none")
        source_rendering = compare(source, source, format=run.format).output_markdown("none")
        if cm.tag_lines(rendered, "accept") != cm.tag_lines(test_rendering, "accept"):
            failures["accept"].append(run.name)
        rejected = cm.tag_lines(rendered, "reject")
        expected = cm.tag_lines(source_rendering, "reject")
        if cm.loose(rejected) != cm.loose(expected):
            failures["order_loose"].append(run.name)
        if rejected != expected:
            failures["order_strict"].append(run.name)
    return failures


@pytest.fixture(scope="module")
def none_oracle() -> dict[str, list[str]]:
    return _none_oracle()


def test_accepting_every_mark_gives_the_test_rendering_on_all_60_runs(
    none_oracle: dict[str, list[str]],
) -> None:
    assert none_oracle["accept"] == []


def test_rejecting_every_mark_gives_the_source_in_source_order_on_59_of_60_runs(
    none_oracle: dict[str, list[str]],
) -> None:
    """Up to whitespace and a leading syntax head or list marker on each line.

    The one exception: csa-1.1-to-2.0's clause 2.1 is labelled ``2.1`` in the
    source and ``2.1.`` in the test, with the same text. A change label drops
    one trailing full stop, so the two labels are equal, the pair produces no
    change node, and a block with no node carries no mark: the test's ``2.1.``
    is drawn plain, and rejecting every mark cannot give back the source's
    ``2.1``. It appeared once the readers kept labels as written (#175).
    """
    assert none_oracle["order_loose"] == ["benchmark/hand/csa-1.1-to-2.0"]


def test_rejecting_every_mark_gives_the_source_exactly_on_49_of_60_runs(
    none_oracle: dict[str, list[str]],
) -> None:
    """The 11 strict failures, all loose matches but csa-1.1-to-2.0, have two causes.

    An unchanged run carries the test's whitespace at a change boundary
    (``course_lesson6``, ``whitespace_after_equal``, ``msa-text-heavy``, the
    table cells of ``msa-markdown-table`` and ``msa-markdown-mixed``), or a
    line's syntax head comes from the test block: an ordered list whose numbers
    shifted, or numbered paragraphs that became list items (``csa`` and
    ``sla``).
    """
    assert none_oracle["order_strict"] == [
        "tests/corpus/course_lesson6",
        "tests/corpus/whitespace_after_equal",
        "benchmark/synthetic/adr-moves-mixed",
        "benchmark/synthetic/msa-markdown-mixed",
        "benchmark/synthetic/msa-markdown-move-heavy",
        "benchmark/synthetic/msa-markdown-renumber-storm",
        "benchmark/synthetic/msa-markdown-structure",
        "benchmark/synthetic/msa-markdown-table",
        "benchmark/synthetic/msa-text-heavy",
        "benchmark/hand/csa-1.1-to-2.0",
        "benchmark/hand/sla-1.0-to-2.0",
    ]


# --- the signature ------------------------------------------------------------------------


@pytest.fixture(scope="module")
def four_kinds() -> Comparison:
    return case("four_kinds")


def test_the_default_style_is_red_green(four_kinds: Comparison) -> None:
    assert four_kinds.output_markdown() == four_kinds.output_markdown("red_green")


def test_a_style_is_a_member_or_its_value(four_kinds: Comparison) -> None:
    for member in MarkdownStyle:
        assert four_kinds.output_markdown(member) == four_kinds.output_markdown(member.value)


def test_markdown_style_gains_no_member() -> None:
    """The pinned tests/test_corpus.py opens a golden for every member; a seventh would fail it."""
    assert [member.value for member in MarkdownStyle] == list(STYLES[:-1])


@pytest.mark.parametrize("style", [None, "red-green", "RED", "critic", "", 7, MarkdownStyle])
def test_any_other_style_raises_value_error_naming_the_accepted_ones(
    four_kinds: Comparison, style: object
) -> None:
    with pytest.raises(ValueError) as raised:
        four_kinds.output_markdown(style)  # type: ignore[arg-type]
    for name in STYLES:
        assert repr(name) in str(raised.value)


@pytest.mark.parametrize("style", [*STYLES[:-1], *MarkdownStyle])
@pytest.mark.parametrize("keyword", ["ins_class", "del_class"])
def test_a_class_with_any_style_but_custom_css_raises_value_error(
    four_kinds: Comparison, style: str, keyword: str
) -> None:
    with pytest.raises(ValueError, match="custom_css"):
        four_kinds.output_markdown(style, **{keyword: "mine"})


def test_custom_css_defaults_its_classes_and_takes_others_one_at_a_time(
    four_kinds: Comparison,
) -> None:
    assert four_kinds.output_markdown("custom_css") == four_kinds.output_markdown(
        "custom_css", ins_class="redline-inserted", del_class="redline-deleted"
    )
    added = four_kinds.output_markdown("custom_css", ins_class="added")
    assert "<span class='added'>sixty (60</span>" in added
    assert "<span class='redline-deleted'>thirty (30</span>" in added
    removed = four_kinds.output_markdown("custom_css", del_class="removed")
    assert "<span class='removed'>thirty (30</span>" in removed
    assert "<span class='redline-inserted'>sixty (60</span>" in removed
    # An empty class is written as given, as 0.6 writes it.
    assert "<span class=''>sixty (60</span>" in four_kinds.output_markdown("custom_css", ins_class="")


# --- what is drawn ------------------------------------------------------------------------


FOUR_KINDS_TEST = (
    "## 1. Delivery\n\n"
    "1.1 The Supplier shall deliver the goods within sixty (60) days of each order.\n\n"
    "1.2 The Buyer may reject goods that do not match the order.\n\n"
    "## 2. Payment\n\n"
    "2.1 The Buyer shall pay each invoice within fourteen days of receiving it.\n\n"
    "2.2 Risk in the goods passes to the Buyer when the goods are unloaded at the Buyer's warehouse."
)


def test_a_filtered_comparison_marks_only_its_own_nodes(four_kinds: Comparison) -> None:
    """The same test document, with only the filter's nodes marked (ADR-0037, rule 1)."""
    modified = four_kinds.filter(kinds=("modify",)).output_markdown("none")
    assert modified == FOUR_KINDS_TEST.replace(
        "within sixty (60) days", "within <del>thirty (30</del><ins>sixty (60</ins>) days"
    )
    moved = four_kinds.filter(kinds=("move",)).output_markdown("none").split("\n\n")
    assert [line for line in moved if "<" in line] == [
        "<del>1.2 Risk in the goods passes to the Buyer when the goods are unloaded at the Buyer's warehouse.</del>",
        "<ins>2.2 Risk in the goods passes to the Buyer when the goods are unloaded at the Buyer's warehouse.</ins>",
    ]
    assert "Late payments" not in "\n".join(moved)  # the delete is not this filter's
    nothing = four_kinds.filter(kinds=("renumber",))
    assert list(nothing.changes) == []
    assert nothing.output_markdown("none") == FOUR_KINDS_TEST
    assert nothing.output_markdown("none") == case_on_itself("four_kinds")


def case_on_itself(name: str) -> str:
    test = read(CASES / name / "test.md")
    return compare(test, test, format="markdown", alignment=GOLDEN_ALIGNMENT).output_markdown("none")


def test_the_syntax_follows_the_test_document_s_format(twins: dict[str, Comparison]) -> None:
    """Markdown in, markdown out; text in, no line syntax."""
    markdown = twins["md"].output_markdown("none").split("\n\n")
    text = twins["txt"].output_markdown("none").split("\n\n")
    assert "## 1. Background" in markdown and "1. Background" in text
    assert not any(line.startswith(("#", "|")) for line in text)


def test_a_comparison_with_no_changes_renders_the_document_unmarked() -> None:
    test = read(SAMPLE / "test.md")
    rendered = compare(test, test, format="markdown").output_markdown("none")
    assert "<ins>" not in rendered and "<del>" not in rendered
    assert rendered.startswith("# Master Services Agreement\n\n")
    assert not rendered.endswith("\n")


# --- the backends and determinism ---------------------------------------------------------


@pytest.mark.skipif(importlib.util.find_spec("rapidfuzz") is None, reason="needs the [fuzzy] extra")
@pytest.mark.parametrize("name", CASE_NAMES)
def test_difflib_and_rapidfuzz_render_each_renderer_case_alike(name: str) -> None:
    """The goldens are difflib's; rapidfuzz would have written the same bytes."""
    renders = [
        [
            case(name, AlignmentConfig(similarity=backend)).output_markdown(style)
            for style in STYLES
        ]
        for backend in ("difflib", "rapidfuzz")
    ]
    assert renders[0] == renders[1]


def test_a_round_tripped_comparison_renders_the_same_bytes(twins: dict[str, Comparison]) -> None:
    """The renderer reads only what survives ``to_dict(include_alignment=True)`` (ADR-0037, rule 7)."""
    for comparison in (*twins.values(), case("nested_move")):
        rebuilt = Comparison.from_dict(comparison.to_dict(include_alignment=True))
        for style in STYLES:
            assert rebuilt.output_markdown(style) == comparison.output_markdown(style)


def test_the_sample_pair_renders_the_same_bytes_under_every_hash_seed() -> None:
    script = """
import sys
from pathlib import Path
from redlines.alignment import AlignmentConfig
from redlines.comparison import compare
sample = Path("tests/corpus/sample_pair")
styles = ("red_green", "none", "red", "ghfm", "bbcode", "streamlit", "custom_css")
for ext, fmt in (("md", "markdown"), ("txt", "text")):
    source = (sample / f"source.{ext}").read_text(encoding="utf-8")
    test = (sample / f"test.{ext}").read_text(encoding="utf-8")
    comparison = compare(source, test, format=fmt, alignment=AlignmentConfig(similarity="difflib"))
    for style in styles:
        sys.stdout.write(comparison.output_markdown(style) + "\\n=====\\n")
"""
    output = assert_byte_identical_across_hash_seeds(script, cwd=REPO_ROOT)
    assert output.count("\n=====\n") == 14
    assert "<ins>" in output and "[b][color=green]" in output
