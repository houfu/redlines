"""Tests for the plain-text reader and the PRD section 6b hard cases (#102).

The hard cases at the bottom are the ones PRD section 6b names and gate 0
requires from day one: four must pass, three are `pytest.mark.xfail` with the
reason they are out of 1.0's plain-text reader. Each has a fixture under
``tests/corpus/hard_cases/``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from redlines.blocks import (
    MATCHED_BY_CONTINUATION,
    MATCHED_BY_DOCUMENT,
    MATCHED_BY_FALLBACK,
    Block,
    BlockKind,
)
from redlines.profiles import Profile, load_profile, profile_from_mapping
from redlines.readers import (
    DEFAULT_MAX_CHARS,
    ParagraphReader,
    Reader,
    reader_for,
    readers,
)
from redlines.readers.text import (
    WRAP_MIN_CHARS,
    Paragraph,
    PlainTextReader,
    normalise,
    segment,
)

EXAMPLE_PROFILE = Path(__file__).parent / "profiles" / "example_contract.yaml"
HARD_CASES = Path(__file__).parent / "corpus" / "hard_cases"

CONTRACT = """\
MASTER SERVICES AGREEMENT

This agreement is made between Acme Analytics Ltd (the "Supplier") and
Beta Retail plc (the "Customer").

7. PAYMENT

7.1 The Customer shall pay each invoice within thirty days of receipt.

The Supplier issues invoices monthly in arrears.

(a) Invoices are sent by email.

(b) Payment is made by bank transfer.

SCHEDULE 1

1. The Services comprise hosting and support.
"""


@pytest.fixture
def profile() -> Profile:
    """The worked example profile: decimal, alpha-paren and roman-paren labels."""
    return load_profile(EXAMPLE_PROFILE)


@pytest.fixture
def mixed_profile() -> Profile:
    """A profile that also knows word-prefixed labels, for the mixed-styles case."""
    return profile_from_mapping(
        {
            "name": "mixed-styles",
            "label_patterns": [
                {
                    "name": "word",
                    "pattern": r"^((?:Article|Section|Part)\s+\d+)\.?\s+",
                    "style": "word",
                },
                {
                    "name": "decimal",
                    "pattern": r"^(\d+(?:\.\d+)*)\.?\s+",
                    "style": "decimal",
                    "depth_mode": "arithmetic",
                },
                {
                    "name": "alpha_paren",
                    "pattern": r"^\(([a-z])\)\s+",
                    "style": "alpha",
                },
                {
                    "name": "roman_paren",
                    "pattern": r"^\(([ivxlcdm]+)\)\s+",
                    "style": "roman",
                },
            ],
            "heading_resets": [
                {"name": "schedule", "pattern": r"(?i)^(schedule|annex|appendix)\b"}
            ],
        }
    )


def read(name: str, profile: Profile) -> Block:
    """Read one hard-case fixture and return its root block."""
    text = (HARD_CASES / f"{name}.txt").read_text(encoding="utf-8")
    return PlainTextReader().read(text, profile=profile).root


def labelled(root: Block, label: str) -> list[Block]:
    """Return every block carrying ``label``, in document order."""
    return [block for block in _walk(root) if block.label == label]


def only(blocks: list[Block]) -> Block:
    """Return the one block in ``blocks``, failing loudly if there is not exactly one."""
    assert len(blocks) == 1, f"expected exactly one block, got {len(blocks)}"
    return blocks[0]


def _walk(block: Block) -> list[Block]:
    """Return ``block`` and its descendants in document order."""
    found = [block]
    for child in block.children:
        found.extend(_walk(child))
    return found


# --- the reader as a reader ------------------------------------------------


def test_the_plain_text_reader_is_a_reader() -> None:
    assert isinstance(PlainTextReader(), Reader)
    assert PlainTextReader().name == "text"
    assert PlainTextReader().formats == ("text",)


def test_it_has_taken_over_the_text_format() -> None:
    """Importing `redlines.readers` registers it in place of the placeholder."""
    assert isinstance(reader_for("text"), PlainTextReader)
    assert readers()["text"].name == "text"


def test_the_placeholder_survives_as_the_degrade_path() -> None:
    """`ParagraphReader` is no longer registered, but it still works (#105)."""
    tree = ParagraphReader().read(CONTRACT)

    assert tree.fallback_count == len(tree.root.children) > 0
    assert tree.root.attrs == {"reader": "paragraph"}


def test_without_a_profile_it_degrades_to_one_block_per_paragraph() -> None:
    degraded = PlainTextReader().read(CONTRACT).root
    placeholder = ParagraphReader().read(CONTRACT).root

    assert [(block.kind, block.text) for block in degraded.children] == [
        (block.kind, block.text) for block in placeholder.children
    ]
    assert {block.matched_by for block in degraded.children} == {MATCHED_BY_FALLBACK}
    assert {block.confidence for block in degraded.children} == {0.0}


def test_the_degraded_root_says_it_had_no_profile() -> None:
    root = PlainTextReader().read(CONTRACT).root

    assert root.matched_by == MATCHED_BY_DOCUMENT
    assert root.attrs["profile"] is None
    assert root.attrs["reader"] == "text"


def test_it_reads_utf_8_bytes(profile: Profile) -> None:
    tree = PlainTextReader().read("1. Fee: 1,000.".encode("utf-8"), profile=profile)

    assert tree.root.children[0].text == "Fee: 1,000."


def test_bytes_that_are_not_utf_8_are_refused(profile: Profile) -> None:
    with pytest.raises(ValueError, match="not UTF-8"):
        PlainTextReader().read(b"\xff\xfe\x00A", profile=profile)


def test_the_size_cap_is_enforced_here(profile: Profile) -> None:
    """ADR-0028: the reader bounds the text because it cannot bound the patterns."""
    with pytest.raises(ValueError, match="over the 100 character limit"):
        PlainTextReader().read("x" * 101, profile=profile, max_chars=100)

    assert PlainTextReader().read("x" * 100, profile=profile, max_chars=100)


def test_the_cap_defaults_to_the_shared_one(profile: Profile) -> None:
    assert PlainTextReader().read("x" * 10, profile=profile) is not None
    assert DEFAULT_MAX_CHARS == 2_000_000


def test_the_same_input_reads_identically_every_time(profile: Profile) -> None:
    """N1: no dict order, set order or stack reuse leaking into the output."""
    first = PlainTextReader().read(CONTRACT, profile=profile)
    second = PlainTextReader().read(CONTRACT, profile=profile)

    assert first == second
    assert first.to_dict() == second.to_dict()


def test_one_reader_instance_holds_no_state_between_reads(profile: Profile) -> None:
    reader = PlainTextReader()
    first = reader.read(CONTRACT, profile=profile)
    reader.read("SCHEDULE 9\n\n(a) An item.\n", profile=profile)

    assert reader.read(CONTRACT, profile=profile) == first


def test_every_block_is_addressed(profile: Profile) -> None:
    tree = PlainTextReader().read(CONTRACT, profile=profile)

    assert tree.root.path == "/"
    for block in tree.walk():
        assert tree.block_at(block.path) == block


def test_the_breadcrumb_leads_back_through_the_headings(profile: Profile) -> None:
    tree = PlainTextReader().read(CONTRACT, profile=profile)
    clause = only(labelled(tree.root, "(b)"))

    assert tree.heading_breadcrumb(clause.path)[-1] == "PAYMENT"


# --- stage 1: normalise and segment ----------------------------------------


def test_crlf_and_cr_line_endings_normalise(profile: Profile) -> None:
    windows = "7. PAYMENT\r\n\r\n7.1 The fee is due.\r\n"
    unix = "7. PAYMENT\n\n7.1 The fee is due.\n"

    assert PlainTextReader().read(windows, profile=profile).to_dict() == (
        PlainTextReader().read(unix, profile=profile).to_dict()
    )
    assert normalise("a\r\nb\rc")[0] == "a\nb\nc"


def test_a_page_break_is_a_paragraph_break() -> None:
    assert normalise("one\ftwo")[0] == "one\n\ntwo"


def test_exotic_spaces_become_ordinary_ones() -> None:
    assert normalise("7.1 The fee.")[0] == "7.1 The fee."


def test_trailing_whitespace_cannot_fake_a_non_blank_line() -> None:
    assert normalise("one\n   \ntwo")[0] == "one\n\ntwo"


def test_control_characters_are_removed_and_reported(profile: Profile) -> None:
    tree = PlainTextReader().read("7.1 The\x00 fee\x07 is due.", profile=profile)

    assert [(d.kind, d.count) for d in tree.dropped] == [("control_character", 2)]
    assert "\x00" not in tree.root.children[0].text


def test_a_clean_document_drops_nothing(profile: Profile) -> None:
    assert PlainTextReader().read(CONTRACT, profile=profile).dropped == ()


def test_hard_wrapped_lines_are_rejoined(profile: Profile) -> None:
    text = (
        "7.1 The Supplier shall provide the Services with reasonable\n"
        "skill and care at all times.\n"
    )

    block = PlainTextReader().read(text, profile=profile).root.children[0]

    assert block.text == (
        "The Supplier shall provide the Services with reasonable skill and "
        "care at all times."
    )
    assert block.attrs["rejoined_lines"] == 2


def test_a_finished_sentence_is_not_rejoined(profile: Profile) -> None:
    text = "The first sentence ends here.\nThe second one starts here.\n"

    root = PlainTextReader().read(text, profile=profile).root

    assert [block.text for block in root.children] == [
        "The first sentence ends here.",
        "The second one starts here.",
    ]


def test_a_wrapped_line_starting_with_a_capital_is_still_rejoined(
    profile: Profile,
) -> None:
    """PRD section 6b's "begins lowercase" is a confirmation, not a requirement."""
    text = "1. This agreement is between Acme Analytics Ltd and\nBeta Retail plc.\n"

    assert PlainTextReader().read(text, profile=profile).root.children[0].text == (
        "This agreement is between Acme Analytics Ltd and Beta Retail plc."
    )


def test_a_capitalised_line_does_not_join_a_short_label_led_heading(
    profile: Profile,
) -> None:
    """PRD section 6b's lowercase half, and the commonest plain-text clause shape.

    "2. Charges" ends without a full stop, but it is a clause heading, not half
    a sentence: joining the body under it to it would lose the body as a block
    of its own, which is the one thing the re-join rule must never do.
    """
    text = "2. Charges\nThe Client shall pay the Fees within thirty days.\n"

    root = PlainTextReader().read(text, profile=profile).root
    blocks = _walk(root)

    assert [block.text for block in blocks if block.kind is BlockKind.HEADING] == [
        "Charges"
    ]
    assert [block.text for block in blocks if block.kind is BlockKind.PARAGRAPH] == [
        "The Client shall pay the Fees within thirty days."
    ]


def test_the_two_spellings_of_a_clause_heading_give_the_same_tree(
    profile: Profile,
) -> None:
    """A blank line between heading and body is optional, so it changes nothing."""
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

    assert (
        PlainTextReader().read(single, profile=profile).to_dict()
        == PlainTextReader().read(blank, profile=profile).to_dict()
    )


def test_a_lowercase_line_joins_however_short_the_line_above(
    profile: Profile,
) -> None:
    """The PRD rule itself: a lower-case start is the wrap, whatever precedes it."""
    text = "1. Charges and\ninvoicing are dealt with here.\n"

    block = PlainTextReader().read(text, profile=profile).root.children[0]

    assert block.text == "Charges and invoicing are dealt with here."
    assert block.attrs["rejoined_lines"] == 2


def test_a_capitalised_line_does_not_join_a_short_unlabelled_heading(
    profile: Profile,
) -> None:
    """The same guard with no label to strip: "Charges" is heading-shaped alone."""
    text = "Charges\nThe Client shall pay the Fees within thirty days.\n"

    paragraphs = segment(normalise(text)[0], profile=profile)

    assert [paragraph.text for paragraph in paragraphs] == [
        "Charges",
        "The Client shall pay the Fees within thirty days.",
    ]


def test_a_long_line_ending_mid_sentence_still_joins_a_proper_noun(
    profile: Profile,
) -> None:
    """The case the wrap rule is protecting: a wrap resuming on a party name."""
    text = (
        "This agreement is made between Acme Analytics Ltd (the 'Supplier') and\n"
        "Beta Retail plc (the 'Customer').\n"
    )

    paragraphs = segment(normalise(text)[0], profile=profile)

    assert len(paragraphs) == 1
    assert paragraphs[0].rejoined is True


def test_the_wrap_length_gate_is_the_documented_constant(profile: Profile) -> None:
    """A line one character short of the gate does not take the line below it."""
    tail = "x" * (WRAP_MIN_CHARS - len("Alpha beta gamma and ") - 1)
    short = f"Alpha beta gamma and {tail}"
    assert len(short) == WRAP_MIN_CHARS - 1

    joined = segment(normalise(f"{short}y\nDelta follows.\n")[0], profile=profile)
    split = segment(normalise(f"{short}\nDelta follows.\n")[0], profile=profile)

    assert len(joined) == 1
    assert len(split) == 2


def test_a_shouting_line_is_never_glued_to_the_line_above(profile: Profile) -> None:
    """The guard that keeps a running header out of the sentence it interrupts."""
    text = "the Customer shall not transfer data\nACME MASTER SERVICES AGREEMENT\n"

    assert len(PlainTextReader().read(text, profile=profile).root.children) == 2


def test_a_label_starts_a_new_paragraph_without_a_blank_line(profile: Profile) -> None:
    text = "7.1 The first clause.\n7.2 The second clause.\n7.3 The third clause.\n"

    root = PlainTextReader().read(text, profile=profile).root

    assert [block.label for block in root.children] == ["7.1", "7.2", "7.3"]


def test_segment_reports_what_it_built(profile: Profile) -> None:
    paragraphs = segment(
        normalise("  (a) one and\n  two\n\n(b) three\n")[0], profile=profile
    )

    assert paragraphs == (
        Paragraph(text="(a) one and two", indent=2, lines=2, rejoined=True),
        Paragraph(text="(b) three", indent=0, lines=1, rejoined=False),
    )


# --- stages 2 to 5, as a tree ----------------------------------------------


def test_labels_are_stripped_and_kept(profile: Profile) -> None:
    clause = only(labelled(read("alpha_roman_ambiguity", profile), "7.1"))

    assert clause.kind is BlockKind.LIST_ITEM
    assert clause.text.startswith("The Customer shall pay")
    assert clause.matched_by == "label:decimal"
    assert clause.confidence == 0.9


def test_every_stage_records_what_it_decided(profile: Profile) -> None:
    """PRD section 6b: a mis-parse has to be visible in the tree."""
    clause = only(labelled(read("alpha_roman_ambiguity", profile), "(j)"))

    assert clause.attrs["label_pattern"] == "alpha_paren"
    assert clause.attrs["label_style"] == "alpha"
    assert clause.attrs["label_depth_mode"] == "stack"
    assert clause.attrs["level_reason"] == "reopen"
    assert clause.attrs["style_reason"] == "only"
    assert clause.attrs["numbering_run"] == "sequence"
    assert clause.attrs["heading_score"] == 0.0
    assert clause.attrs["heading_signals"] == ["too_many_words"]
    assert clause.attrs["indent"] == 0


def test_the_root_reports_the_whole_read(profile: Profile) -> None:
    root = read("schedule_numbering_restart", profile)

    assert root.attrs == {
        "reader": "text",
        "profile": "example-contract",
        "paragraphs": 13,
        "labelled": 9,
        "headings": 6,
        "numbering_resets": 2,
    }


def test_an_unlabelled_paragraph_continues_the_clause_above_it(
    profile: Profile,
) -> None:
    tree = PlainTextReader().read(CONTRACT, profile=profile)
    clause = only(labelled(tree.root, "7.1"))
    body = clause.children[0]

    assert body.kind is BlockKind.PARAGRAPH
    assert body.text == "The Supplier issues invoices monthly in arrears."
    assert body.matched_by == MATCHED_BY_CONTINUATION
    assert body.attrs["continuation_reason"] == "follows_label"
    assert 0.3 <= body.confidence < 0.7


def test_a_paragraph_with_no_clause_above_it_falls_back(profile: Profile) -> None:
    tree = PlainTextReader().read(CONTRACT, profile=profile)
    recital = [
        block
        for block in tree.walk()
        if block.text.startswith("This agreement is made")
    ]

    assert only(recital).matched_by == MATCHED_BY_FALLBACK
    assert only(recital).confidence == 0.0
    assert tree.fallback_count == 1


def test_a_heading_opens_a_section_that_holds_what_follows(profile: Profile) -> None:
    tree = PlainTextReader().read(CONTRACT, profile=profile)
    heading = only([b for b in tree.walk() if b.text == "PAYMENT"])

    assert heading.kind is BlockKind.HEADING
    assert heading.label == "7"
    assert heading.attrs["heading_score"] > heading.attrs["heading_threshold"]
    section = tree.block_at(heading.path.rsplit("/", 1)[0])
    assert section.kind is BlockKind.SECTION
    assert [child.label for child in section.children] == ["7", "7.1"]


def test_a_stray_year_is_read_as_a_label_but_reported_as_a_doubtful_one(
    profile: Profile,
) -> None:
    """ADR-0028's worked example of what the reader owns and a profile cannot.

    A bare-number pattern matches ``2019 saw…`` exactly as well as it matches a
    clause number. The reader is the only thing that sees the whole run, so the
    difference has to show up in the confidence and in ``attrs``.
    """
    tree = PlainTextReader().read(
        "1. First.\n\n2019 saw a change.\n\n2. Second.\n", profile=profile
    )
    first, stray, second = (only(labelled(tree.root, x)) for x in ("1", "2019", "2"))

    assert stray.confidence < first.confidence == second.confidence
    assert stray.attrs["numbering_run"] == "out_of_sequence"
    assert first.attrs["numbering_run"] == "first_value"
    assert second.attrs["numbering_run"] == "sequence"


def test_a_title_case_heading_opens_a_section_over_its_prose(
    profile: Profile,
) -> None:
    """A section titled "Governing Law" heads what follows as surely as capitals."""
    tree = PlainTextReader().read(
        "Governing Law\n\nThis agreement is governed by the laws of England.\n",
        profile=profile,
    )
    heading = only([block for block in tree.walk() if block.text == "Governing Law"])

    assert heading.kind is BlockKind.HEADING
    assert heading.attrs["heading_signals"] == [
        "title_case",
        "no_terminal_punctuation",
        "short",
    ]
    section = tree.block_at(heading.path.rsplit("/", 1)[0])
    assert section.kind is BlockKind.SECTION
    assert section.children[1].text.startswith("This agreement is governed")


def test_a_reset_heading_says_which_rule_reset_it(profile: Profile) -> None:
    tree = PlainTextReader().read(CONTRACT, profile=profile)
    heading = only([b for b in tree.walk() if b.text == "SCHEDULE 1"])

    assert heading.matched_by == "heading:schedule"
    assert heading.attrs["heading_reset"] == "schedule"
    assert heading.confidence == 0.75


def test_levels_are_the_documents_own_numbering(profile: Profile) -> None:
    root = read("alpha_roman_ambiguity", profile)

    assert only(labelled(root, "7")).level == 1
    assert only(labelled(root, "7.1")).level == 2
    assert only(labelled(root, "(a)")).level == 3


def test_the_tree_round_trips_through_json(profile: Profile) -> None:
    tree = PlainTextReader().read(CONTRACT, profile=profile)

    assert json.loads(json.dumps(tree.to_dict())) == tree.to_dict()


# --- PRD section 6b hard cases: the four that must pass --------------------


def test_hard_case_alpha_roman_ambiguity(profile: Profile) -> None:
    """``(i)`` after ``(h)`` is alphabetic; ``(i)`` after ``7.2`` is roman."""
    root = read("alpha_roman_ambiguity", profile)
    alpha_i, roman_i = labelled(root, "(i)")

    assert alpha_i.attrs["label_style"] == "alpha"
    assert alpha_i.attrs["style_reason"] == "sequence"
    assert alpha_i.level == only(labelled(root, "(h)")).level == 3

    assert roman_i.attrs["label_style"] == "roman"
    assert roman_i.attrs["style_reason"] == "first_value"
    assert roman_i.level == only(labelled(root, "(ii)")).level == 3

    assert alpha_i.attrs["label_candidates"] == ["alpha_paren", "roman_paren"]
    assert roman_i.confidence < alpha_i.confidence < 0.7


def test_hard_case_numbering_restarts_inside_a_schedule(profile: Profile) -> None:
    """The reset is what makes the schedule's own ``1.`` a level-1 clause again."""
    root = read("schedule_numbering_restart", profile)
    sections = [block for block in root.children if block.kind is BlockKind.SECTION]
    body, _charges, first_schedule, second_schedule = sections

    assert body.children[0].text == "SERVICES"
    assert first_schedule.children[0].matched_by == "heading:schedule"
    assert second_schedule.children[0].matched_by == "heading:schedule"

    ones = labelled(root, "1")
    assert [block.level for block in ones] == [1, 1, 1]
    assert len({block.path for block in ones}) == 3
    assert root.attrs["numbering_resets"] == 2


def test_hard_case_one_line_clauses_that_look_like_headings(profile: Profile) -> None:
    """A short title-case line heads what follows -- or is a clause of its own."""
    root = read("one_line_clause_headings", profile)

    heading = only(labelled(root, "9"))
    assert heading.kind is BlockKind.HEADING
    assert "followed_by_deeper_label" in heading.attrs["heading_signals"]

    for label in ("10", "11"):
        clause = only(labelled(root, label))
        assert clause.kind is BlockKind.LIST_ITEM
        assert "followed_by_peer_label" in clause.attrs["heading_signals"]
        assert 0.0 < clause.attrs["heading_score"] < clause.attrs["heading_threshold"]

    assert only(labelled(root, "12")).kind is BlockKind.HEADING


def test_hard_case_two_label_styles_in_one_document(mixed_profile: Profile) -> None:
    """Two drafters, two vocabularies: both are read and neither breaks the other."""
    root = read("mixed_label_styles", mixed_profile)

    section_one = only(labelled(root, "Section 1"))
    assert section_one.attrs["label_style"] == "word"
    assert section_one.level == 1
    assert section_one.kind is BlockKind.HEADING

    assert only(labelled(root, "1.1")).level == 2
    assert only(labelled(root, "(a)")).level == 3
    assert only(labelled(root, "(a)")).attrs["label_style"] == "alpha"

    # "Section 2" is followed by a decimal label at its own level rather than
    # under it, so nothing hangs from it and it stays a clause -- the honest
    # reading of a document whose two drafters disagreed.
    section_two = only(labelled(root, "Section 2"))
    assert section_two.kind is BlockKind.LIST_ITEM
    assert section_two.level == 1
    assert only(labelled(root, "2")).level == 1
    assert only(labelled(root, "2.1")).level == 2


def test_the_hard_cases_are_read_deterministically(
    profile: Profile, mixed_profile: Profile
) -> None:
    for fixture in sorted(HARD_CASES.glob("*.txt")):
        text = fixture.read_text(encoding="utf-8")
        for active in (profile, mixed_profile, None):
            first = PlainTextReader().read(text, profile=active)
            assert (
                first.to_dict()
                == PlainTextReader().read(text, profile=active).to_dict()
            )


# --- PRD section 6b hard cases: the three that are out of scope ------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Definitions written as one run-on paragraph need sentence-level "
        "splitting the semantic pass owns (#104), not the five mechanical "
        "stages: the reader sees one labelled paragraph and says so."
    ),
)
def test_hard_case_definitions_as_a_run_on_paragraph(profile: Profile) -> None:
    root = read("definitions_run_on", profile)
    clause = only(labelled(root, "1.1"))

    assert len(clause.children) == 4


@pytest.mark.xfail(
    strict=True,
    reason=(
        "A cross-reference in prose ('the preceding sub-clause') is a span the "
        "semantic pass resolves against the tree (#104, R1b); the reader has "
        "no spans and carries no reference."
    ),
)
def test_hard_case_cross_references_in_prose(profile: Profile) -> None:
    root = read("cross_references_in_prose", profile)
    clause = only(labelled(root, "4.2"))

    assert [span.value for span in clause.spans] == ["4.1"]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Page headers interleaved by a PDF text extractor are 1.1 work "
        "(R8a): the reader must not crash on them, which "
        "test_pdf_page_headers_do_not_crash_the_reader asserts, but the "
        "structure around them is wrong."
    ),
)
def test_hard_case_pdf_page_headers_interleaved(profile: Profile) -> None:
    root = read("pdf_page_headers", profile)
    clause = only(labelled(root, "7.1"))

    assert "Page 3 of 12" not in [block.text for block in _walk(root)]
    assert clause.text.endswith("consent of the Customer.")


def test_pdf_page_headers_do_not_crash_the_reader(profile: Profile) -> None:
    """The part of the PDF case that is in scope: it reads, and it reports."""
    tree = PlainTextReader().read(
        (HARD_CASES / "pdf_page_headers.txt").read_text(encoding="utf-8"),
        profile=profile,
    )

    assert only(labelled(tree.root, "7.1")).level == 2
    assert only(labelled(tree.root, "7.2")).level == 2
    assert tree.fallback_count > 0
