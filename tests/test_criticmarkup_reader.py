r"""The reference reader on hand-written strings (``tests/helpers/criticmarkup.py``).

The renderer tests use this reader as their oracle, so its own behaviour is
pinned here, one ADR-0037 step at a time, on text no renderer produced.
"""

from __future__ import annotations

import pytest

from tests.helpers import criticmarkup as cm
from tests.helpers.criticmarkup import Token


# --- step 1: parse ------------------------------------------------------------


def test_each_construct_parses_to_its_token() -> None:
    assert cm.parse("a{++b++}c{--d--}e{~~f~>g~~}h{>>i<<}") == (
        Token("text", "a"),
        Token("insert", "b"),
        Token("text", "c"),
        Token("delete", "d"),
        Token("text", "e"),
        Token("substitution", "f", "g"),
        Token("text", "h"),
        Token("note", "i"),
    )


def test_an_odd_run_makes_the_whole_opener_literal() -> None:
    assert cm.parse("\\{++x++}") == (Token("text", "{++x++}"),)
    assert cm.parse("\\\\\\{++x++\\}") == (Token("text", "\\{++x++}"),)


def test_an_even_run_before_an_opener_is_halved_and_the_opener_is_live() -> None:
    assert cm.parse("a\\\\{++x++}") == (Token("text", "a\\"), Token("insert", "x"))


def test_a_mark_ends_at_the_first_live_closer() -> None:
    assert cm.parse("{++a++\\}b++}") == (Token("insert", "a++}b"),)
    assert cm.parse("{++a+++}") == (Token("insert", "a+"),)
    assert cm.parse("{--a----}") == (Token("delete", "a--"),)


def test_a_body_ending_in_a_doubled_run_is_halved() -> None:
    assert cm.parse("{--old\\\\--}") == (Token("delete", "old\\"),)


def test_a_substitution_old_side_ends_at_the_first_live_separator() -> None:
    assert cm.parse("{~~a~\\>b~>c~~}") == (Token("substitution", "a~>b", "c"),)
    assert cm.parse("{~~a~~>b~~}") == (Token("substitution", "a~", "b"),)


def test_closers_outside_a_mark_are_literal() -> None:
    assert cm.parse("x++\\} and a~\\>") == (Token("text", "x++} and a~>"),)


def test_an_unterminated_mark_is_an_error() -> None:
    with pytest.raises(cm.CriticMarkupError):
        cm.parse("{++never closed")
    with pytest.raises(cm.CriticMarkupError):
        cm.parse("{~~old side only~~}")


def test_critic_unescape_leaves_an_even_run_alone() -> None:
    assert cm.critic_unescape("x++\\}") == "x++}"
    assert cm.critic_unescape("x++\\\\}") == "x++\\\\}"


# --- steps 2 and 3: resolve, strip notes --------------------------------------


def test_accept_and_reject_keep_opposite_sides() -> None:
    tokens = cm.parse("a {++b ++}{--c --}{~~d~>e~~} f")
    assert cm.resolve(tokens, "accept") == "a b e f"
    assert cm.resolve(tokens, "reject") == "a c d f"


def test_a_note_goes_with_the_space_after_it_when_text_follows_with_one() -> None:
    assert cm.resolve(cm.parse("{>>renumbered from 3.<<} text"), "accept") == "text"


def test_a_note_goes_with_the_space_before_it_otherwise() -> None:
    assert cm.resolve(cm.parse("text {>>moved from 1.2 /a<<}"), "accept") == "text"
    assert cm.resolve(cm.parse("{>>origin<<}"), "reject") == ""


# --- steps 5 and 6: roles, line starts ----------------------------------------


@pytest.mark.parametrize(
    ("line", "stripped", "role"),
    [
        ("[clause] 1.1 Text", "1.1 Text", "clause"),
        ("## [heading%20role] Title", "## Title", "heading role"),
        ("3. [schedule] text", "3. text", "schedule"),
        ("    - [a%5Db] nested", "    - nested", "a]b"),
        ("> - [quote] quoted item", "> - quoted item", "quote"),
        ("\\[clause] escaped", "\\[clause] escaped", None),
        ("[Party A] shall", "[Party A] shall", None),
        ("text [clause] later", "text [clause] later", None),
    ],
)
def test_split_role_removes_one_prefix_after_the_syntax_head(
    line: str, stripped: str, role: str | None
) -> None:
    result, decoded, _ = cm.split_role(line)
    assert (result, decoded) == (stripped, role)


def test_only_one_role_prefix_is_removed() -> None:
    assert cm.read_line("[clause] [x] task") == "[x] task"


def test_the_line_start_is_unescaped_after_the_role_is_stripped() -> None:
    assert cm.read_line("\\[x] task") == "[x] task"
    assert cm.read_line("\\\\\\[x] task") == "\\[x] task"
    assert cm.read_line("- \\[x] task") == "- [x] task"
    assert cm.read_line("[clause] \\[x] task") == "[x] task"
    assert cm.read_line("\\\\[x] task") == "\\\\[x] task"


def test_the_content_start_after_a_stripped_role_is_not_re_read_as_a_head() -> None:
    """``[clause] 1. \\[x]``: the content starts at ``1.``, so the backslash stays."""
    assert cm.read_line("[clause] 1. \\[x] task") == "1. \\[x] task"


def test_without_roles_nothing_is_stripped_or_unescaped() -> None:
    assert cm.lines("[clause] \\[x] task", "accept", roles=False) == ["[clause] \\[x] task"]


# --- step 7: the residue rule ---------------------------------------------------


def test_residue_drops_what_a_removed_mark_leaves_behind() -> None:
    assert cm.residue(
        [
            "  kept  ",
            "",
            "   ",
            "## ",
            "- ",
            "1.",
            ">",
            "> - ",
            "|  |  |",
            "| a |  |",
        ]
    ) == ["kept", "| a |  |"]


def test_residue_drops_an_alignment_row_with_no_table_row_beside_it() -> None:
    assert cm.residue(["| --- | :---: |", "text"]) == ["text"]
    assert cm.residue(["| a | b |", "| --- | :---: |"]) == ["| a | b |", "| --- | :---: |"]
    assert cm.residue(["| --- |", "| x |"]) == ["| --- |", "| x |"]


def test_residue_drops_a_fence_whose_body_is_empty() -> None:
    assert cm.residue(["```python", "", "```", "after"]) == ["after"]
    assert cm.residue(["> ````", "> ", "> ````"]) == []
    assert cm.residue(["```", "body", "```", "```", "```"]) == ["```", "body", "```"]


# --- the comparisons -------------------------------------------------------------


def test_exact_multiset_and_loose() -> None:
    assert cm.exact(["a", "b"], ["a", "b"])
    assert not cm.exact(["a", "b"], ["b", "a"])
    assert cm.multiset(["a", "b"], ["b", "a"])
    assert not cm.multiset(["a", "b"], ["a  ", "b"])
    assert cm.loose(["## 1. A  heading", "3. 4. item", "- x y"]) == ["Aheading", "item", "xy"]
    assert cm.loose_multiset(["1. foo (bar)"], ["2. foo(bar)"])


def test_accept_all_and_reject_all_compose_every_step() -> None:
    annotated = "[clause] {++1.2 New.++}\n\n[clause] 1.1 Kept {~~old~>new~~}. {>>moved from 1.1 /x<<}"
    assert cm.accept_all(annotated) == ["1.2 New.", "1.1 Kept new."]
    assert cm.reject_all(annotated) == ["1.1 Kept old."]


def test_tag_lines_reads_the_legacy_none_style() -> None:
    rendered = "a <del>b </del><ins>c </ins>d\n\n<ins>new</ins>"
    assert cm.tag_lines(rendered, "accept") == ["a c d", "new"]
    assert cm.tag_lines(rendered, "reject") == ["a b d"]
