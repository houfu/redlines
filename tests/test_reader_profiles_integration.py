"""The plain-text reader meeting the shipped profiles, over the § 6b hard cases.

`tests/test_text_reader.py` reads the hard cases under the worked example
profile and inline mapping profiles, and `tests/test_builtin_profiles.py` reads
the shipped YAML without a reader. Neither runs the pair together, which is
where the defects this file pins were found: a `contract` pattern that could
not produce the roman reading of ``(i)`` at all, a re-join rule that swallowed
the body of a one-line clause heading, and -- once that pattern was widened --
a stack tie-break that read ``(x)`` after ``(v)`` back out to the alpha run.

So: every built-in profile against every fixture in ``tests/corpus/hard_cases/``
-- no crash, the same tree twice, and a fallback count that says what each
profile claims to be able to read -- plus the three sentences PRD § 6b writes
about ``(i)`` and the clause-heading shape, asserted through the reader.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from redlines.blocks import (
    MATCHED_BY_DOCUMENT,
    MATCHED_BY_FALLBACK,
    Block,
    BlockKind,
    BlockTree,
)
from redlines.profiles import BUILTIN_PROFILE_NAMES, Profile, builtin_profile
from redlines.readers import reader_for
from redlines.readers.text import PlainTextReader

HARD_CASES = Path(__file__).parent / "corpus" / "hard_cases"

#: Every hard-case fixture, by stem, sorted so the parametrisation is stable.
FIXTURES = [path.stem for path in sorted(HARD_CASES.glob("*.txt"))]

#: The one fixture whose structure is allowed to be wrong: page headers
#: interleaved by a PDF text extractor are 1.1 work (R8a, gate 0's third
#: strict xfail). The reader must read it; it need not read it correctly.
OUT_OF_SCOPE = "pdf_page_headers"


# --- helpers ---------------------------------------------------------------


def source(name: str) -> str:
    """Return the text of the named hard-case fixture."""
    return (HARD_CASES / f"{name}.txt").read_text(encoding="utf-8")


def read(text: str, profile_name: str) -> BlockTree:
    """Read ``text`` with the registered text reader under a built-in profile."""
    return reader_for("text").read(text, profile=builtin_profile(profile_name))


def walk(tree: BlockTree) -> list[Block]:
    """Return every block in ``tree``, in document order."""
    return list(tree.walk())


def labelled(tree: BlockTree, label: str) -> list[Block]:
    """Return every block carrying ``label``, in document order."""
    return [block for block in tree.walk() if block.label == label]


def only(blocks: list[Block]) -> Block:
    """Return the one block in ``blocks``, failing loudly if there is not one."""
    assert len(blocks) == 1, f"expected exactly one block, got {len(blocks)}"
    return blocks[0]


@pytest.fixture
def contract() -> Profile:
    """The shipped `contract` profile, which is the default for plain text."""
    return builtin_profile("contract")


# --- every profile over every fixture --------------------------------------


@pytest.mark.parametrize("fixture", FIXTURES)
@pytest.mark.parametrize("profile_name", BUILTIN_PROFILE_NAMES)
def test_every_builtin_profile_reads_every_hard_case(
    profile_name: str, fixture: str
) -> None:
    """No crash, a rooted tree, and every paragraph of the fixture accounted for."""
    tree = read(source(fixture), profile_name)

    assert tree.root.kind is BlockKind.DOCUMENT
    assert tree.root.matched_by == MATCHED_BY_DOCUMENT
    assert tree.root.attrs["profile"] == profile_name
    assert tree.root.attrs["paragraphs"] > 0
    assert tree.dropped == ()
    assert len(walk(tree)) > 1


@pytest.mark.parametrize("fixture", FIXTURES)
@pytest.mark.parametrize("profile_name", BUILTIN_PROFILE_NAMES)
def test_every_read_is_deterministic(profile_name: str, fixture: str) -> None:
    """N1: the same input and profile give an identical tree, twice over."""
    text = source(fixture)

    first = PlainTextReader().read(text, profile=builtin_profile(profile_name))
    second = PlainTextReader().read(text, profile=builtin_profile(profile_name))

    assert first.to_dict() == second.to_dict()


@pytest.mark.parametrize("fixture", FIXTURES)
@pytest.mark.parametrize("profile_name", BUILTIN_PROFILE_NAMES)
def test_every_block_reports_itself_within_the_adr_0030_bands(
    profile_name: str, fixture: str
) -> None:
    """`fallback` and 0.0 travel together, and nothing else claims 0.0."""
    tree = read(source(fixture), profile_name)

    for block in walk(tree):
        assert 0.0 <= block.confidence <= 1.0
        assert (block.matched_by == MATCHED_BY_FALLBACK) == (block.confidence == 0.0)
    assert tree.fallback_count == sum(
        1 for block in walk(tree) if block.matched_by == MATCHED_BY_FALLBACK
    )


@pytest.mark.parametrize("fixture", FIXTURES)
def test_contract_recognises_every_hard_case_it_claims(fixture: str) -> None:
    """`contract` is the plain-text default, so a contract fixture is its job.

    Nothing falls through on the six in-scope fixtures. The PDF one is allowed
    to, and is the fixture gate 0 marks xfail: a running header is not a clause
    and the reader is right to say it recognised nothing.
    """
    tree = read(source(fixture), "contract")

    if fixture == OUT_OF_SCOPE:
        assert tree.fallback_count > 0
    else:
        assert tree.fallback_count == 0


@pytest.mark.parametrize("fixture", FIXTURES)
def test_generic_claims_nothing_and_says_so(fixture: str) -> None:
    """`generic` declares no labels, so every paragraph is a fallback (D30)."""
    tree = read(source(fixture), "generic")
    blocks = walk(tree)

    assert tree.fallback_count > 0
    assert tree.fallback_count > read(source(fixture), "contract").fallback_count
    assert [block.label for block in blocks if block.label is not None] == []
    assert tree.fallback_count == sum(
        1 for block in blocks if block.kind is BlockKind.PARAGRAPH
    )


# --- PRD § 6b on "(i)": the three sentences, through the reader -------------
#
# "Alpha and roman labels are ambiguous in isolation ('(i)' after '(h)' is
# alphabetic; after '7.2' it is roman and one level deeper), so depth is
# resolved from the label-style stack... Headings the profile marks as
# numbering resets... clear the stack, which is what makes labels unambiguous
# again after a schedule boundary."


def test_an_i_after_an_h_is_alphabetic(contract: Profile) -> None:
    """Sentence one: the alpha run reaches its ninth item."""
    tree = reader_for("text").read(source("alpha_roman_ambiguity"), profile=contract)
    alpha_i, _roman_i = labelled(tree, "(i)")

    assert alpha_i.attrs["label_style"] == "alpha"
    assert alpha_i.matched_by == "label:alpha_paren"
    assert alpha_i.attrs["style_reason"] == "sequence"
    assert alpha_i.level == only(labelled(tree, "(h)")).level
    # Both patterns claimed it; the stack chose, and the block records both.
    assert alpha_i.attrs["label_candidates"] == ["alpha_paren", "roman_paren"]
    assert 0.3 <= alpha_i.confidence < 0.7


def test_an_i_after_a_decimal_is_roman_and_one_level_deeper(
    contract: Profile,
) -> None:
    """Sentence two, and the first defect: it used to come back alpha at level 3
    with ``(ii)`` stranded a level below it, because `contract`'s roman pattern
    needed two letters and so could never claim a bare ``(i)``."""
    text = "7.2 Sub clause\n(i) first\n(ii) second\n"

    tree = reader_for("text").read(text, profile=contract)
    parent = only(labelled(tree, "7.2"))
    first = only(labelled(tree, "(i)"))
    second = only(labelled(tree, "(ii)"))

    assert parent.level == 2
    assert first.matched_by == "label:roman_paren"
    assert first.attrs["label_style"] == "roman"
    assert first.attrs["style_reason"] == "first_value"
    assert first.level == parent.level + 1 == 3
    assert second.matched_by == "label:roman_paren"
    assert second.level == first.level == 3
    assert 0.3 <= first.confidence < 0.7


def test_a_gap_in_a_roman_sub_list_stays_in_the_sub_list(contract: Profile) -> None:
    """The third defect: ``(x)`` after ``(v)`` popped back out to the alpha run.

    Widening `contract`'s ``roman_paren`` to one letter or more (the fix for
    the first defect) made every one of ``i v x l c d m`` ambiguous, not just
    ``(i)``. With an alpha run and a roman run both open and neither continued
    exactly, the tie fell to profile order and ``(x)`` came back
    ``label:alpha_paren`` at the alpha level, closing the sub-list.
    """
    text = (
        "7.2 Sub clause\n"
        "(a) alpha one\n"
        "(b) alpha two\n"
        "(i) roman one\n"
        "(ii) roman two\n"
        "(iii) roman three\n"
        "(iv) roman four\n"
        "(v) roman five\n"
        "(x) roman ten\n"
    )

    tree = reader_for("text").read(text, profile=contract)
    alpha_b = only(labelled(tree, "(b)"))
    roman_v = only(labelled(tree, "(v)"))
    roman_x = only(labelled(tree, "(x)"))

    assert roman_x.matched_by == "label:roman_paren"
    assert roman_x.attrs["label_style"] == "roman"
    assert roman_x.level == roman_v.level == alpha_b.level + 1
    # The road not taken is still on the record, at the low band ADR-0030
    # reserves for a call the numbering only half supports.
    assert roman_x.attrs["label_candidates"] == ["alpha_paren", "roman_paren"]
    assert 0.3 <= roman_x.confidence < 0.5


def test_a_schedule_heading_clears_the_stack_so_i_is_roman_again(
    contract: Profile,
) -> None:
    """Sentence three: the same ``(i)`` reads alpha before the boundary and roman
    after it, because the reset emptied the stack that was deciding."""
    text = (
        "7. PAYMENT\n"
        "\n"
        "(h) Each party bears its own banking charges.\n"
        "\n"
        "(i) Interest accrues on any overdue amount.\n"
        "\n"
        "SCHEDULE 1\n"
        "\n"
        "(i) The Supplier hosts the Customer Data.\n"
        "\n"
        "(ii) Availability is measured monthly.\n"
    )

    tree = reader_for("text").read(text, profile=contract)
    before, after = labelled(tree, "(i)")

    assert before.attrs["label_style"] == "alpha"
    assert after.attrs["label_style"] == "roman"
    assert after.level == 1 < before.level
    assert tree.root.attrs["numbering_resets"] == 1
    schedule = only(labelled(tree, "SCHEDULE 1"))
    assert schedule.kind is BlockKind.HEADING
    assert schedule.matched_by == "heading:schedule"


def test_the_schedule_fixture_restarts_at_level_one_under_contract() -> None:
    """The same rule over the fixture: three separate ``1.`` clauses, all level 1."""
    tree = read(source("schedule_numbering_restart"), "contract")

    ones = labelled(tree, "1")
    assert [block.level for block in ones] == [1, 1, 1]
    assert len({block.path for block in ones}) == 3
    assert tree.root.attrs["numbering_resets"] == 2


# --- PRD § 6b on re-joining wraps: the second defect ------------------------


def test_a_clause_heading_keeps_its_body_as_its_own_block(contract: Profile) -> None:
    """The second defect: "2. Charges" used to swallow the line below it.

    A label-led line with its body on the next line is one of the commonest
    plain-text contract shapes, and re-joining it produced a single
    ``list_item`` reading "Charges The Client shall pay...".
    """
    text = (
        "2. Charges\n"
        "The Client shall pay the Fees within thirty days.\n"
        "\n"
        "3. Term\n"
        "This Agreement starts on the Effective Date.\n"
    )

    tree = reader_for("text").read(text, profile=contract)
    blocks = walk(tree)

    assert [block.text for block in blocks if block.kind is BlockKind.HEADING] == [
        "Charges",
        "Term",
    ]
    assert [block.text for block in blocks if block.kind is BlockKind.PARAGRAPH] == [
        "The Client shall pay the Fees within thirty days.",
        "This Agreement starts on the Effective Date.",
    ]
    assert [block.label for block in blocks if block.label is not None] == ["2", "3"]


def test_the_blank_line_is_optional_between_a_clause_heading_and_its_body(
    contract: Profile,
) -> None:
    """Both spellings of the same document give the same tree, addresses included."""
    single = (
        "2. Charges\n"
        "The Client shall pay the Fees within thirty days.\n"
        "\n"
        "3. Term\n"
        "This Agreement starts on the Effective Date.\n"
    )
    blank = (
        "2. Charges\n"
        "\n"
        "The Client shall pay the Fees within thirty days.\n"
        "\n"
        "3. Term\n"
        "\n"
        "This Agreement starts on the Effective Date.\n"
    )

    read_single = reader_for("text").read(single, profile=contract)
    read_blank = reader_for("text").read(blank, profile=contract)

    assert read_single.to_dict() == read_blank.to_dict()


def test_a_genuine_hard_wrap_still_joins_under_contract(contract: Profile) -> None:
    """The case the widened rule protects: a wrap resuming on a party name."""
    text = (
        'This agreement is made between Acme Analytics Ltd (the "Supplier") and\n'
        'Beta Retail plc (the "Customer").\n'
    )

    tree = reader_for("text").read(text, profile=contract)
    paragraphs = [block for block in walk(tree) if block.kind is BlockKind.PARAGRAPH]

    assert len(paragraphs) == 1
    assert paragraphs[0].text.endswith('Beta Retail plc (the "Customer").')
    assert paragraphs[0].attrs["rejoined_lines"] == 2


def test_the_pdf_fixtures_wrapped_sentence_still_joins() -> None:
    """The lowercase half of the PRD rule, over the fixture that leans on it."""
    tree = read(source(OUT_OF_SCOPE), "contract")

    clause = only(labelled(tree, "7.1"))
    assert clause.text.startswith("The Supplier shall process Personal Data")
    assert "instructions of the Customer" in clause.text
    assert clause.attrs["rejoined_lines"] == 2
