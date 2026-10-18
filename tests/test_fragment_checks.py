"""The checks of ``tests/helpers/fragment_checks.py`` catch what they claim (ADR-0038).

A check that never fails proves nothing about the fragments it passes, so each
one is run here against markup that breaks it: hand-written strings for the
parse, the allowlist and the stylesheet, and one real change list
(``four_kinds``) with a single thing altered for the checks that need a
comparison. Each altered fragment must fail with the check's own message, and
the unaltered one must pass.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import pytest

from redlines.alignment import AlignmentConfig
from redlines.comparison import SCHEMA_VERSION, Comparison, compare
from redlines.filters import ChangeFilter
from tests.helpers import fragment_checks as fc

CASES = Path(__file__).parent / "renderer_cases"

ROOT = (
    '<section class="redlines" data-redlines-view="changes" '
    f'data-redlines-fragment="1.0" data-redlines-schema="{SCHEMA_VERSION}">'
)


def _var(name: str, standard: str, own: str) -> str:
    return f"var(--redlines-{name},var({standard},{own}))"


FG = _var("fg", "--color-text-primary", "light-dark(#141413,#FAF9F5)")
BORDER = _var("border", "--color-border-tertiary", "light-dark(#1F1E1D26,#DEDCD126)")

GOOD_CSS = "\n".join(
    (
        ".redlines{font-family:"
        "var(--redlines-font,var(--font-sans,system-ui,sans-serif));"
        f"color:{FG};background:var(--redlines-bg,transparent)}}",
        f".redlines .redlines-change+.redlines-change{{border-top:1px solid {BORDER}}}",
        ".redlines code{font-family:"
        "var(--redlines-mono,var(--font-mono,ui-monospace,monospace))}",
        ".redlines .redlines-role{color:"
        + _var("muted", "--color-text-secondary", "light-dark(#3D3D3A,#C2C0B6)")
        + "}",
        ".redlines .redlines-notice{color:"
        + _var("warn-fg", "--color-text-warning", "light-dark(#5A4815,#D1A041)")
        + "}",
        ".redlines .redlines-note{color:"
        + _var("move-fg", "--color-text-info", "light-dark(#3266AD,#80AADD)")
        + "}",
        ".redlines .redlines-table{border-collapse:collapse}",
        ".redlines ins{color:"
        + _var("ins-fg", "--color-text-success", "light-dark(#265B19,#7AB948)")
        + ";background:"
        + _var("ins-bg", "--color-background-success", "light-dark(#E9F1DC,#1B4614)")
        + ";border-radius:var(--redlines-radius,var(--border-radius-sm,4px))}",
        ".redlines del{color:"
        + _var("del-fg", "--color-text-danger", "light-dark(#7F2C28,#EE8884)")
        + ";background:"
        + _var("del-bg", "--color-background-danger", "light-dark(#F7ECEC,#602A28)")
        + "}",
    )
)
BUTTON = (
    '<button type="button" class="redlines-fullscreen" '
    'data-redlines-action="fullscreen" hidden>Full screen</button>'
)


def wrap(body: str, *, css: str = GOOD_CSS, root: str = ROOT) -> str:
    return f"{root}\n<style>{css}</style>\n{body}\n</section>"


# --- F1: well formed ----------------------------------------------------------


def test_a_minimal_fragment_parses_to_its_root() -> None:
    root = fc.check_well_formed(wrap("<p>x &amp; y</p>"))
    assert root.tag == "section"
    assert root.elements()[1].text() == "x & y"


@pytest.mark.parametrize(
    ("fragment", "message"),
    [
        (wrap("<p>never closed"), "unclosed"),
        (wrap("</p>"), "stray </p>"),
        (wrap("<p><span>x</p></span>"), "stray </p>"),
        (wrap("<span/>"), "self-closing"),
        (wrap("<!-- a comment -->"), "a comment"),
        (wrap("<p>x</p>") + "trailing text", "text outside the root"),
        (wrap("") + wrap(""), "2 root elements"),
        ("<!DOCTYPE html>" + wrap(""), "a declaration"),
    ],
)
def test_f1_rejects_markup_that_is_not_one_well_formed_root(
    fragment: str, message: str
) -> None:
    with pytest.raises(fc.FragmentError, match=re.escape(message)):
        fc.check_well_formed(fragment)


@pytest.mark.parametrize(
    ("root", "message"),
    [
        (
            '<div class="redlines" data-redlines-view="changes" '
            'data-redlines-fragment="1.0" '
            f'data-redlines-schema="{SCHEMA_VERSION}">',
            "not a <section>",
        ),
        (ROOT.replace(' data-redlines-schema="2.0"', ""), "the root's attributes"),
        (ROOT.replace('fragment="1.0"', 'fragment="2.0"'), "data-redlines-fragment"),
        (ROOT.replace('view="changes"', 'view="other"'), "data-redlines-view"),
        (
            ROOT.replace('class="redlines"', 'class="redlines extra"'),
            "the root's class",
        ),
    ],
)
def test_f1_requires_the_root_and_its_three_attributes(root: str, message: str) -> None:
    fragment = wrap("", root=root)
    if root.startswith("<div"):
        fragment = fragment.replace("</section>", "</div>")
    with pytest.raises(fc.FragmentError, match=re.escape(message)):
        fc.check_well_formed(fragment)


# --- F2: self-contained and CSP-safe ---------------------------------------------


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("<script>alert(1)</script>", "a forbidden element"),
        ('<img src="x">', "a forbidden element"),
        ("<iframe></iframe>", "a forbidden element"),
        ("<svg></svg>", "a forbidden element"),
        ('<a href="https://example.com">x</a>', "outside the allowlist"),
        ("<h2>Heading</h2>", "outside the allowlist"),
        ('<p onclick="alert(1)">x</p>', "an inline handler"),
        ('<p style="color:red">x</p>', "an inline style"),
        ('<p id="x">x</p>', "an id"),
        ('<button formaction="x">x</button>', "a URL-bearing"),
        ('<p title="x">x</p>', "outside the allowlist"),
        ('<p class="a" class="b">x</p>', "a repeated attribute"),
        ("<style>.redlines{}</style>", "2 <style> elements"),
        ('<span role="button">x</span>', "role='button'"),
        ('<span role="heading" aria-level="2">x</span>', "role='heading'"),
        ('<p role="heading">x</p>', "a heading with no aria-level"),
        ('<p role="heading" aria-level="7">x</p>', "aria-level='7'"),
        ('<p aria-level="2">x</p>', "aria-level='2'"),
        ('<button type="submit">x</button>', "type='submit'"),
        ('<span type="button">x</span>', "type='button'"),
        ('<p hidden="false">x</p>', "hidden carries a value"),
    ],
)
def test_f2_rejects_what_the_allowlist_does_not_allow(body: str, message: str) -> None:
    root = fc.check_well_formed(wrap(body))
    with pytest.raises(fc.FragmentError, match=re.escape(message)):
        fc.check_self_contained(root)


def test_f2_requires_the_style_to_be_the_first_child() -> None:
    fragment = f"{ROOT}\n<p>first</p>\n<style>{GOOD_CSS}</style>\n</section>"
    with pytest.raises(fc.FragmentError, match="first child"):
        fc.check_self_contained(fc.check_well_formed(fragment))


@pytest.mark.parametrize(
    "css",
    [
        '@import "x.css";',
        ".redlines{background:url(x.png)}",
        '.redlines{background-image:image-set("https://example.com/x.png" 1x)}',
        '.redlines{background-image:-webkit-image-set("x.png" 1x)}',
        '.redlines{list-style-image:image("x.png")}',
        '.redlines{cursor:src("x.cur"),auto}',
        '.redlines{background:cross-fade("a.png","b.png",50%)}',
        ".redlines{background:-moz-element(#page)}",
    ],
)
def test_f2_rejects_an_external_reference_in_the_stylesheet(css: str) -> None:
    with pytest.raises(fc.FragmentError, match="the stylesheet contains"):
        fc.check_self_contained(fc.check_well_formed(wrap("", css=css)))


def test_f2_accepts_the_allowlist_and_returns_the_stylesheet() -> None:
    body = (
        '<header class="redlines-header"><p data-x="1">x</p>' + BUTTON + "</header>"
        '<p class="redlines-block" role="heading" aria-level="2">x</p>'
    )
    assert fc.check_self_contained(fc.check_well_formed(wrap(body))) == GOOD_CSS


def test_the_hook_is_one_hidden_button_with_no_handler() -> None:
    fc.check_hooks(fc.check_well_formed(wrap(BUTTON)))
    for broken in (BUTTON.replace(" hidden", ""), BUTTON + BUTTON, ""):
        with pytest.raises(fc.FragmentError, match="button"):
            fc.check_hooks(fc.check_well_formed(wrap(broken)))


# --- F3 and F4: the stylesheet ----------------------------------------------------


def test_f3_accepts_a_stylesheet_that_reads_all_thirteen_names() -> None:
    assert fc.check_theme(GOOD_CSS) == set(fc.STANDARD_VARIABLES)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ((f"color:{FG}", "color:red"), "a colour outside"),
        ((f"color:{FG}", "color:#141413"), "a colour outside"),
        ((f"color:{FG}", "color:var(--redlines-fg,#141413)"), "is not one var()"),
        (
            (
                f"color:{FG}",
                "color:var(--redlines-fg,"
                "var(--color-text-secondary,light-dark(#000,#fff)))",
            ),
            "falls back to --color-text-secondary",
        ),
        (
            (f"color:{FG}", "color:var(--redlines-fg,var(--color-text-primary,#000))"),
            "light-dark()",
        ),
        (
            (f"color:{FG}", "color:var(--color-text-primary,light-dark(#000,#fff))"),
            "not --redlines-*",
        ),
        (
            (
                f"color:{FG}",
                "color:var(--redlines-accent,var(--x,light-dark(#000,#fff)))",
            ),
            "not one of the thirteen",
        ),
        (
            (
                "background:var(--redlines-bg,transparent)",
                "background:var(--redlines-bg,white)",
            ),
            "not transparent",
        ),
        (
            (f"border-top:1px solid {BORDER}", f"border-top:1px wavy {BORDER}"),
            "'wavy' beside",
        ),
        (
            (f"border-top:1px solid {BORDER}", "border-top:1px solid black"),
            "a colour outside",
        ),
        ((f"color:{FG}", f"color:{FG};--redlines-fg:red"), "custom property"),
        ((f"color:{FG}", f"color:{FG};color-scheme:light dark"), "color-scheme"),
        ((f"color:{FG}", f"color:{FG};line-height:{FG}"), "not a theme property"),
        (
            (";border-radius:var(--redlines-radius,var(--border-radius-sm,4px))", ""),
            "missing ['radius']",
        ),
    ],
)
def test_f3_rejects_a_declaration_the_theme_does_not_reach(
    change: tuple[str, str], message: str
) -> None:
    old, new = change
    assert old in GOOD_CSS
    with pytest.raises(fc.FragmentError, match=re.escape(message)):
        fc.check_theme(GOOD_CSS.replace(old, new, 1))


@pytest.mark.parametrize(
    "css",
    [
        "@media (prefers-color-scheme:dark){.redlines{color:red}}",
        ".redlines{color:red}/* x */",
    ],
)
def test_f3_reads_only_a_flat_stylesheet(css: str) -> None:
    with pytest.raises(fc.FragmentError):
        fc.rules(css)


@pytest.mark.parametrize(
    "selector",
    [
        ".redlines-change",
        "p",
        "ins",
        ".redlines :root",
        ".redlines body p",
        "html .redlines",
        "*",
        ".redlines+p",
        ".redlines~*",
        ".redlines:not(.x) ~ div",
        ".redlines:is(.a,.b)+p",
        '.redlines[data-x="a"]~p',
    ],
)
def test_f4_rejects_a_selector_that_reaches_the_page(selector: str) -> None:
    with pytest.raises(fc.FragmentError, match="selector"):
        fc.check_scoped(GOOD_CSS + "\n" + selector + "{margin:0}")


@pytest.mark.parametrize(
    "selector",
    [
        ".redlines",
        ".redlines .redlines-change",
        '.redlines[data-redlines-display="fullscreen"]',
        ".redlines>p",
        '.redlines [data-x="body"]',
        ".redlines .redlines-change+.redlines-change",
        ".redlines:has(+ p) p",
        '.redlines[data-x="~"] p',
        ".redlines::before",
    ],
)
def test_f4_accepts_a_selector_scoped_under_the_root(selector: str) -> None:
    fc.check_scoped(selector + "{margin:0}")


# --- F5 to F9: on a real change list with one thing altered -------------------------


@lru_cache(maxsize=None)
def four_kinds() -> Comparison:
    directory = CASES / "four_kinds"
    with open(directory / "source.md", encoding="utf-8", newline="") as source:
        with open(directory / "test.md", encoding="utf-8", newline="") as test:
            return compare(
                source.read(),
                test.read(),
                format="markdown",
                alignment=AlignmentConfig(similarity="difflib"),
            )


def test_the_unaltered_change_list_passes() -> None:
    comparison = four_kinds()
    root = fc.check_change_list(comparison.output_html(), comparison)
    assert fc.check_filter_parity(root, comparison) > 20


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (' data-index="1"', ' data-index="7"', "attributes"),
        (' data-kind="insert"', ' data-kind="added"', "attributes"),
        (
            ' data-role="clause" data-matched-by="label"',
            ' data-matched-by="label" data-role="clause"',
            "out of order",
        ),
        (' data-confidence="0.8667"', ' data-confidence="0.87"', "attributes"),
        ("<details><summary>", "<details> <summary>", "<details> does not hold"),
        (
            '</span><span class="redlines-excerpt">',
            '</span> <span class="redlines-excerpt">',
            "whitespace",
        ),
        (
            '<code class="redlines-address">',
            '<span class="redlines-address">',
            "not a <code>",
        ),
        ("label 0.8667</span>", "label 0.9</span>", "the match reads"),
    ],
)
def test_f5_rejects_a_row_that_does_not_carry_its_node(
    old: str, new: str, message: str
) -> None:
    comparison = four_kinds()
    fragment = comparison.output_html()
    assert old in fragment
    altered = fragment.replace(old, new, 1)
    if old.startswith("<code"):
        altered = altered.replace("</code>", "</span>", 1)
    with pytest.raises(fc.FragmentError, match=re.escape(message)):
        root = fc.check_well_formed(altered)
        fc.check_rows(root, comparison)


def test_f5_counts_the_rows() -> None:
    comparison = four_kinds()
    fragment = comparison.output_html()
    rows = re.findall(r"\n<li .*?</li>", fragment, flags=re.S)
    with pytest.raises(fc.FragmentError, match="3 rows for 4 changes"):
        fc.check_rows(
            fc.check_well_formed(fragment.replace(rows[-1], "", 1)), comparison
        )


def test_f6_fails_when_an_attribute_disagrees_with_the_filter() -> None:
    comparison = four_kinds()
    fragment = comparison.output_html().replace(
        ' data-chars="10"', ' data-chars="3"', 1
    )
    root = fc.check_well_formed(fragment)
    assert fc.select_rows(fc.row_elements(root), ChangeFilter(min_chars=1)) == [0]
    with pytest.raises(fc.FragmentError, match="filter parity fails"):
        fc.check_filter_parity(root, comparison, [ChangeFilter(min_chars=5)])


def test_f6_prefixes_are_segment_aligned() -> None:
    assert fc._prefix_matches("/section[1]/list_item[2]", "/section[1]")
    assert fc._prefix_matches("/section[1]", "/section[1]")
    assert not fc._prefix_matches("/section[11]", "/section[1]")
    assert fc._prefix_matches("/section[11]", "/")
    assert not fc._prefix_matches(None, "/")


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("<ins>sixty (60</ins>", "<ins>seventy (70</ins>", "accept reads"),
        ("<del>thirty (30</del>", "<del>twenty (20</del>", "reject reads"),
        ("do not match the order.</ins>", "do not match.</ins>", "the body reads"),
        ("<ins><span", "<del><span", "the body is not one <ins>"),
    ],
)
def test_f7_rejects_a_body_that_does_not_read_its_node(
    old: str, new: str, message: str
) -> None:
    comparison = four_kinds()
    fragment = comparison.output_html()
    assert old in fragment
    altered = fragment.replace(old, new, 1)
    if new.startswith("<del><span"):
        altered = altered.replace("the order.</ins></div>", "the order.</del></div>", 1)
    with pytest.raises(fc.FragmentError, match=re.escape(message)):
        fc.check_row_texts(fc.check_well_formed(altered), comparison)


def _markdown(source: str, test: str) -> Comparison:
    return compare(
        source, test, format="markdown", alignment=AlignmentConfig(similarity="difflib")
    )


def test_f7_still_fails_a_changed_fence_body() -> None:
    comparison = _markdown("Intro.\n\n```\nline1\nline2\n```", "Intro.")
    fragment = comparison.output_html()
    fc.check_row_texts(fc.check_well_formed(fragment), comparison)
    altered = fragment.replace("line1\nline2</del>", "line1\nline2\nline3</del>", 1)
    assert altered != fragment
    with pytest.raises(fc.FragmentError, match="the body reads"):
        fc.check_row_texts(fc.check_well_formed(altered), comparison)


def test_f7_reads_a_blank_ghost_row_as_deleted_but_not_one_without_its_mark() -> None:
    table = "| A | B |\n| --- | --- |\n"
    comparison = _markdown(table + "|  |  |\n| 1 | 2 |\n", table + "| 1 | 2 |\n")
    fragment = comparison.output_annotated(syntax="html")
    assert "<tr><td><del></del></td><td></td></tr>" in fragment
    fc.check_block_texts(fc.check_well_formed(fragment), comparison)
    unmarked = fragment.replace("<td><del></del></td>", "<td></td>", 1)
    with pytest.raises(fc.FragmentError, match="rows read"):
        fc.check_block_texts(fc.check_well_formed(unmarked), comparison)
    renamed = fragment.replace("<td>1</td>", "<td>one</td>", 1)
    with pytest.raises(fc.FragmentError, match="rows read"):
        fc.check_block_texts(fc.check_well_formed(renamed), comparison)


def test_f7_reads_the_document_view_block_by_block() -> None:
    comparison = four_kinds()
    fragment = comparison.output_annotated(syntax="html")
    fc.check_document(fragment, comparison)
    for old, new, message in (
        ("Late payments carry interest", "Late payments carry no interest", "reads"),
        (
            'aria-level="2" data-test-address="/section[2]/heading[1]"',
            'data-test-address="/section[2]/heading[1]"',
            "role=heading",
        ),
        (
            'data-test-address="/section[2]/list_item[2]" data-source-address',
            "data-source-address",
            "data-kind",
        ),
    ):
        assert old in fragment
        altered = fragment.replace(old, new, 1)
        if "aria-level" in old:
            altered = altered.replace(
                ' role="heading" data-test-address="/section[2]',
                ' data-test-address="/section[2]',
                1,
            )
        with pytest.raises(fc.FragmentError):
            fc.check_block_texts(fc.check_well_formed(altered), comparison)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("4 changes", "4 change", "the counts read"),
        ("1 inserted", "2 inserted", "the counts read"),
        ("similarity difflib", "similarity rapidfuzz", "the configuration line"),
        ("0 of 9 source blocks", "1 of 9 source blocks", "the structure line"),
    ],
)
def test_f8_rejects_a_header_that_misreports(old: str, new: str, message: str) -> None:
    comparison = four_kinds()
    fragment = comparison.output_html()
    with pytest.raises(fc.FragmentError, match=re.escape(message)):
        fc.check_header(fc.check_well_formed(fragment.replace(old, new, 1)), comparison)


def test_f8_wants_each_notice_exactly_when_it_is_true() -> None:
    filtered = four_kinds().filter(kinds=("modify",))
    fragment = filtered.output_html()
    fc.check_header(fc.check_well_formed(fragment), filtered)
    notice = re.search(
        r'\n<p class="redlines-notice" data-notice="filtered">[^\n]*</p>', fragment
    )
    assert notice is not None
    with pytest.raises(fc.FragmentError, match="the notices are"):
        fc.check_header(
            fc.check_well_formed(fragment.replace(notice.group(0), "", 1)), filtered
        )
    unfiltered = four_kinds().output_html()
    forged = unfiltered.replace("\n<button", notice.group(0) + "\n<button", 1)
    with pytest.raises(fc.FragmentError, match="the notices are"):
        fc.check_header(fc.check_well_formed(forged), four_kinds())


def test_f9_catches_a_render_that_changes_between_calls() -> None:
    calls: list[int] = []

    def render(comparison: Comparison) -> str:
        calls.append(1)
        return comparison.output_html() + ("" if len(calls) == 1 else " ")

    with pytest.raises(fc.FragmentError, match="two renders"):
        fc.check_deterministic(render, four_kinds())
