"""Tests for label detection, the style stack, headings and continuations (#102).

These cover `redlines.readers.labels` on its own -- one line of text at a time,
the way the markdown reader (#103) will call it -- while
``tests/test_text_reader.py`` covers the same code driving a whole document.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from redlines.profiles import HeadingRule, Profile, load_profile, profile_from_mapping
from redlines.readers.labels import (
    CONFIDENCE_ARITHMETIC,
    CONFIDENCE_ARITHMETIC_OUT_OF_SEQUENCE,
    CONFIDENCE_STACK,
    CONFIDENCE_STACK_FIRST_VALUE,
    CONFIDENCE_STACK_ORDER,
    CONFIDENCE_STACK_SEQUENCE,
    HEADING_THRESHOLD,
    NEXT_DEEPER,
    NEXT_NONE,
    NEXT_PEER,
    RUN_FIRST_VALUE,
    RUN_OUT_OF_SEQUENCE,
    RUN_SEQUENCE,
    RUN_UNVERIFIED,
    HeadingScore,
    HierarchyStack,
    continuation_for,
    detect_label,
    heading_confidence,
    heading_reset_name,
    heading_score,
    label_candidates,
    sequence_index,
)

EXAMPLE_PROFILE = Path(__file__).parent / "profiles" / "example_contract.yaml"


@pytest.fixture
def profile() -> Profile:
    """The worked example profile: decimal, alpha-paren and roman-paren labels."""
    return load_profile(EXAMPLE_PROFILE)


@pytest.fixture
def word_profile() -> Profile:
    """A profile that also knows word-prefixed labels ("Section 3")."""
    return profile_from_mapping(
        {
            "name": "word-labels",
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
            ],
        }
    )


# --- stage 2: detecting labels ---------------------------------------------


def test_a_decimal_label_is_detected_and_stripped(profile: Profile) -> None:
    match = detect_label("7.2 Disputed invoices are escalated.", profile=profile)

    assert match is not None
    assert (match.name, match.style, match.depth_mode) == (
        "decimal",
        "decimal",
        "arithmetic",
    )
    assert match.label == "7.2"
    assert match.value == "7.2"
    assert match.text == "Disputed invoices are escalated."
    assert match.end == len("7.2 ")


def test_a_trailing_full_stop_is_not_part_of_the_label(profile: Profile) -> None:
    match = detect_label("1. Interpretation", profile=profile)

    assert match is not None
    assert match.label == "1"
    assert match.text == "Interpretation"


def test_a_bracketed_label_keeps_its_brackets(profile: Profile) -> None:
    match = detect_label("(a) Invoices are issued monthly.", profile=profile)

    assert match is not None
    assert (match.label, match.value, match.style) == ("(a)", "a", "alpha")


def test_a_word_label_keeps_its_word(word_profile: Profile) -> None:
    match = detect_label("Section 3. Charges", profile=word_profile)

    assert match is not None
    assert (match.label, match.value, match.style) == ("Section 3", "Section 3", "word")


def test_an_indented_label_is_still_detected(profile: Profile) -> None:
    match = detect_label("        (b) Downtime is excluded.", profile=profile)

    assert match is not None
    assert match.label == "(b)"


def test_an_unlabelled_line_has_no_label(profile: Profile) -> None:
    assert detect_label("The parties agree as follows.", profile=profile) is None


def test_without_a_profile_nothing_is_a_label() -> None:
    assert detect_label("7.2 Disputed invoices.", profile=None) is None
    assert label_candidates("7.2 Disputed invoices.", profile=None) == ()


def test_candidates_come_back_in_profile_order(profile: Profile) -> None:
    candidates = label_candidates("(i) interest accrues daily.", profile=profile)

    assert [candidate.name for candidate in candidates] == [
        "alpha_paren",
        "roman_paren",
    ]


def test_an_unambiguous_label_has_one_candidate(profile: Profile) -> None:
    assert len(label_candidates("(a) Invoices.", profile=profile)) == 1
    assert len(label_candidates("(ii) The parties meet.", profile=profile)) == 1


def test_detect_label_takes_the_profiles_first_match(profile: Profile) -> None:
    """Without context, precedence is all `detect_label` has -- and it says so."""
    match = detect_label("(i) interest accrues daily.", profile=profile)

    assert match is not None
    assert match.name == "alpha_paren"


def test_sequence_index_reads_each_style() -> None:
    assert sequence_index("alpha", "h") == 8
    assert sequence_index("roman", "iv") == 4
    assert sequence_index("decimal", "7.2") == 2
    assert sequence_index("word", "Section 3") == 3
    assert sequence_index("word", "Part IV") == 4
    assert sequence_index("alpha", "aa") is None
    assert sequence_index("roman", "banana") is None


def test_the_same_label_indexes_differently_in_each_style() -> None:
    """``c`` is the third letter and one hundred in roman: the whole problem."""
    assert sequence_index("alpha", "c") == 3
    assert sequence_index("roman", "c") == 100


# --- stage 3: the hierarchy stack ------------------------------------------


def test_a_decimal_label_carries_its_own_depth(profile: Profile) -> None:
    stack = HierarchyStack()

    assert stack.place(label_candidates("7. Payment", profile=profile)).level == 1
    assert stack.place(label_candidates("7.1 The fee.", profile=profile)).level == 2
    assert stack.place(label_candidates("7.1.3 VAT.", profile=profile)).level == 3
    assert stack.place(label_candidates("8. Term", profile=profile)).level == 1


def test_a_decimal_placement_is_a_near_certainty(profile: Profile) -> None:
    placement = HierarchyStack().place(label_candidates("7.2 Fees.", profile=profile))

    assert placement.confidence == CONFIDENCE_ARITHMETIC
    assert placement.level_reason == "arithmetic"
    assert placement.style_reason == "only"
    assert placement.run_reason == RUN_UNVERIFIED
    assert placement.ambiguous is False
    assert placement.considered == ("decimal",)


# --- stage 3: the value against the numbering run --------------------------


def test_a_value_that_contradicts_the_run_is_not_a_near_certainty(
    profile: Profile,
) -> None:
    """ADR-0028 hands the reader the case a profile cannot express: "2019 saw…".

    The label is still read -- it is what the document says -- but nothing about
    it continues the run, and the confidence has to say so.
    """
    stack = HierarchyStack()
    clause = stack.place(label_candidates("1. First.", profile=profile))

    stray = stack.place(label_candidates("2019 saw a change.", profile=profile))

    assert clause.run_reason == RUN_FIRST_VALUE
    assert clause.confidence == CONFIDENCE_ARITHMETIC
    assert stray.match.label == "2019"
    assert stray.run_reason == RUN_OUT_OF_SEQUENCE
    assert stray.confidence == CONFIDENCE_ARITHMETIC_OUT_OF_SEQUENCE
    assert stray.confidence < clause.confidence


def test_an_out_of_sequence_value_does_not_take_the_run_with_it(
    profile: Profile,
) -> None:
    """The clause after a stray year is still the sequel to the clause before it."""
    stack = HierarchyStack()
    stack.place(label_candidates("1. First.", profile=profile))
    stack.place(label_candidates("2019 saw a change.", profile=profile))

    placement = stack.place(label_candidates("2. Second.", profile=profile))

    assert placement.run_reason == RUN_SEQUENCE
    assert placement.confidence == CONFIDENCE_ARITHMETIC


def test_the_run_picks_up_again_after_a_gap(profile: Profile) -> None:
    """A skipped clause number is reported once, not for the rest of the document."""
    stack = HierarchyStack()
    stack.place(label_candidates("1. One.", profile=profile))
    stack.place(label_candidates("2. Two.", profile=profile))

    gap = stack.place(label_candidates("5. Five.", profile=profile))
    after = stack.place(label_candidates("6. Six.", profile=profile))

    assert gap.run_reason == RUN_OUT_OF_SEQUENCE
    assert after.run_reason == RUN_SEQUENCE
    assert after.confidence == CONFIDENCE_ARITHMETIC


def test_a_value_with_no_run_to_check_it_against_is_unverified(
    profile: Profile,
) -> None:
    """A document that starts at clause 7 is an extract, not a mis-parse."""
    placement = HierarchyStack().place(label_candidates("7. Payment", profile=profile))

    assert placement.run_reason == RUN_UNVERIFIED
    assert placement.confidence == CONFIDENCE_ARITHMETIC


def test_a_reset_lets_the_numbering_start_over_without_complaint(
    profile: Profile,
) -> None:
    stack = HierarchyStack()
    stack.place(label_candidates("1. Services.", profile=profile))
    stack.place(label_candidates("2. Charges.", profile=profile))
    stack.reset()

    placement = stack.place(label_candidates("1. Hosting.", profile=profile))

    assert placement.run_reason == RUN_FIRST_VALUE
    assert placement.confidence == CONFIDENCE_ARITHMETIC


def test_the_run_check_never_moves_the_level(profile: Profile) -> None:
    """A label sits where its own depth says, however implausible its value."""
    stack = HierarchyStack()
    stack.place(label_candidates("1. First.", profile=profile))

    stray = stack.place(label_candidates("2019 saw a change.", profile=profile))

    assert stray.level == 1
    assert stray.level_reason == "arithmetic"


def test_the_stack_reports_the_run_for_an_alpha_label_too(profile: Profile) -> None:
    """Reported for every style; only the arithmetic branch prices it in."""
    stack = HierarchyStack()
    stack.place(label_candidates("7.1 The fee.", profile=profile))

    first = stack.place(label_candidates("(a) Monthly.", profile=profile))
    second = stack.place(label_candidates("(b) In arrears.", profile=profile))

    assert first.run_reason == RUN_FIRST_VALUE
    assert second.run_reason == RUN_SEQUENCE
    assert second.confidence == CONFIDENCE_STACK


def test_an_alpha_label_nests_under_the_decimal_above_it(profile: Profile) -> None:
    stack = HierarchyStack()
    stack.place(label_candidates("7.2 Fees.", profile=profile))

    placement = stack.place(label_candidates("(a) Monthly.", profile=profile))

    assert placement.level == 3
    assert placement.level_reason == "push"
    assert placement.confidence == CONFIDENCE_STACK


def test_the_same_alpha_label_nests_shallower_under_a_shallower_decimal(
    profile: Profile,
) -> None:
    stack = HierarchyStack()
    stack.place(label_candidates("7. Payment", profile=profile))

    assert stack.place(label_candidates("(a) Monthly.", profile=profile)).level == 2


def test_a_style_already_open_reopens_at_its_own_level(profile: Profile) -> None:
    stack = HierarchyStack()
    stack.place(label_candidates("7.2 Fees.", profile=profile))
    stack.place(label_candidates("(a) Monthly.", profile=profile))
    stack.place(label_candidates("(i) In arrears.", profile=profile))

    placement = stack.place(label_candidates("(b) Quarterly.", profile=profile))

    assert placement.level == 3
    assert placement.level_reason == "reopen"
    assert stack.styles == ("decimal", "alpha")


def test_a_decimal_label_truncates_the_stack(profile: Profile) -> None:
    stack = HierarchyStack()
    stack.place(label_candidates("7.2 Fees.", profile=profile))
    stack.place(label_candidates("(a) Monthly.", profile=profile))

    assert stack.snapshot() == (("decimal", 2), ("alpha", 3))
    stack.place(label_candidates("7.3 Interest.", profile=profile))
    assert stack.snapshot() == (("decimal", 2),)


def test_the_ambiguous_i_after_h_is_alphabetic(profile: Profile) -> None:
    """PRD section 6b's canonical case, first half."""
    stack = HierarchyStack()
    stack.place(label_candidates("7.1 The fee.", profile=profile))
    for letter in "abcdefgh":
        stack.place(label_candidates(f"({letter}) An item.", profile=profile))

    placement = stack.place(label_candidates("(i) interest accrues.", profile=profile))

    assert placement.match.style == "alpha"
    assert placement.match.name == "alpha_paren"
    assert placement.level == 3
    assert placement.style_reason == "sequence"
    assert placement.ambiguous is True
    assert placement.considered == ("alpha_paren", "roman_paren")
    assert placement.confidence == CONFIDENCE_STACK_SEQUENCE


def test_the_ambiguous_i_after_a_decimal_is_roman_and_one_deeper(
    profile: Profile,
) -> None:
    """PRD section 6b's canonical case, second half."""
    stack = HierarchyStack()
    stack.place(label_candidates("7.2 Disputes.", profile=profile))

    placement = stack.place(
        label_candidates("(i) The Customer notifies.", profile=profile)
    )

    assert placement.match.style == "roman"
    assert placement.level == 3
    assert placement.style_reason == "first_value"
    assert placement.confidence == CONFIDENCE_STACK_FIRST_VALUE
    assert stack.place(label_candidates("(ii) They meet.", profile=profile)).level == 3


def test_i_after_b_opens_a_roman_sub_list(profile: Profile) -> None:
    """``(i)`` is not the successor of ``(b)``, so it starts a list of its own."""
    stack = HierarchyStack()
    stack.place(label_candidates("7.1 The fee.", profile=profile))
    stack.place(label_candidates("(a) Monthly.", profile=profile))
    stack.place(label_candidates("(b) In arrears.", profile=profile))

    placement = stack.place(label_candidates("(i) Interest.", profile=profile))

    assert placement.match.style == "roman"
    assert placement.level == 4


def test_a_roman_c_does_not_hijack_an_alpha_sequence(profile: Profile) -> None:
    stack = HierarchyStack()
    stack.place(label_candidates("(a) Monthly.", profile=profile))
    stack.place(label_candidates("(b) In arrears.", profile=profile))

    placement = stack.place(label_candidates("(c) On demand.", profile=profile))

    assert placement.match.style == "alpha"
    assert placement.level == 1


def test_a_gap_in_an_open_roman_run_does_not_fall_back_to_alpha(
    profile: Profile,
) -> None:
    """``(x)`` after ``(v)`` is the tenth numeral, not the twenty-fourth letter.

    Both styles are open -- an alpha run at ``(b)`` and a roman one at ``(v)``
    inside it -- and ``(x)`` continues neither exactly, so rank alone ties and
    profile order used to hand it to ``alpha_paren``, popping the roman
    sub-clauses shut. The jump decides instead: five in the roman run against
    twenty-two in the alpha one.
    """
    stack = HierarchyStack()
    stack.place(label_candidates("7.2 Fees.", profile=profile))
    for letter in ("a", "b"):
        stack.place(label_candidates(f"({letter}) An item.", profile=profile))
    for numeral in ("i", "ii", "iii", "iv", "v"):
        stack.place(label_candidates(f"({numeral}) A step.", profile=profile))

    placement = stack.place(label_candidates("(x) A tenth step.", profile=profile))

    assert placement.match.style == "roman"
    assert placement.match.name == "roman_paren"
    assert placement.level == 4
    assert placement.style_reason == "open_style"
    assert placement.run_reason == RUN_OUT_OF_SEQUENCE
    assert placement.considered == ("alpha_paren", "roman_paren")
    # Still only a guess: nothing continued its run, so it stays in the low
    # band and both candidates are on the record (ADR-0030).
    assert placement.confidence == CONFIDENCE_STACK_ORDER


def test_a_gap_in_an_open_alpha_run_does_not_jump_to_roman(
    profile: Profile,
) -> None:
    """The mirror image: ``(d)`` after ``(b)`` is a jump of two, not of 497."""
    stack = HierarchyStack()
    stack.place(label_candidates("7.2 Fees.", profile=profile))
    for letter in ("a", "b"):
        stack.place(label_candidates(f"({letter}) An item.", profile=profile))
    for numeral in ("i", "ii", "iii"):
        stack.place(label_candidates(f"({numeral}) A step.", profile=profile))

    placement = stack.place(label_candidates("(d) A fourth item.", profile=profile))

    assert placement.match.style == "alpha"
    assert placement.level == 3


def test_a_reset_makes_the_next_label_level_one_again(profile: Profile) -> None:
    stack = HierarchyStack()
    stack.place(label_candidates("7.2 Fees.", profile=profile))
    stack.place(label_candidates("(a) Monthly.", profile=profile))

    stack.reset()

    assert stack.depth == 0
    assert stack.resets == 1
    assert stack.place(label_candidates("1. The Services.", profile=profile)).level == 1


def test_preview_answers_without_changing_the_stack(profile: Profile) -> None:
    stack = HierarchyStack()
    stack.place(label_candidates("7.2 Fees.", profile=profile))
    before = stack.snapshot()

    preview = stack.preview(label_candidates("(a) Monthly.", profile=profile))

    assert preview.level == 3
    assert stack.snapshot() == before
    assert stack.place(label_candidates("(a) Monthly.", profile=profile)).level == 3


def test_placing_nothing_is_a_programming_error() -> None:
    with pytest.raises(ValueError, match="at least one label candidate"):
        HierarchyStack().place(())


def test_indentation_pops_the_stack_back_for_a_new_style(profile: Profile) -> None:
    """The secondary signal: a new style written back at the margin is not deeper."""
    stack = HierarchyStack()
    stack.place(label_candidates("7.1 The fee.", profile=profile), indent=0)
    stack.place(label_candidates("(a) Monthly.", profile=profile), indent=8)

    placement = stack.place(
        label_candidates("(i) Interest.", profile=profile), indent=0
    )

    assert placement.level_reason == "dedent_push"
    assert placement.level == 3


def test_without_indentation_the_secondary_signal_never_fires(profile: Profile) -> None:
    stack = HierarchyStack()
    stack.place(label_candidates("7.1 The fee.", profile=profile))
    stack.place(label_candidates("(a) Monthly.", profile=profile))

    placement = stack.place(label_candidates("(i) Interest.", profile=profile))

    assert placement.level_reason == "push"
    assert placement.level == 4


# --- stage 5: heading scoring ----------------------------------------------


def test_an_all_caps_line_followed_by_deeper_content_is_a_heading() -> None:
    score = heading_score("PAYMENT", next_label=NEXT_DEEPER)

    assert score.is_heading
    assert score.score == pytest.approx(0.93)
    assert score.signals == (
        "all_caps",
        "no_terminal_punctuation",
        "short",
        "followed_by_deeper_label",
    )


def test_a_title_case_line_followed_by_deeper_content_is_a_heading() -> None:
    assert heading_score("Limitation of Liability", next_label=NEXT_DEEPER).is_heading


def test_a_title_case_heading_stands_up_without_a_label_under_it() -> None:
    """Contracts title sections "Governing Law" as often as "GOVERNING LAW".

    Nothing labelled follows, and a profile has no weight or threshold field to
    make up a shortfall with, so title case has to carry the line on its own.
    """
    score = heading_score("Governing Law", next_label=NEXT_NONE)

    assert score.signals == ("title_case", "no_terminal_punctuation", "short")
    assert score.is_heading


def test_neither_case_signal_is_a_heading_all_by_itself() -> None:
    """The gates narrow; the other signals still have to agree."""
    rule = HeadingRule(forbid_terminal_punctuation=False, max_words=20)

    assert not heading_score(
        "The Charges Are Payable Monthly In Arrears By The Customer On Demand.",
        rule=rule,
    ).is_heading
    assert not heading_score(
        "THE CHARGES ARE PAYABLE MONTHLY IN ARREARS BY THE CUSTOMER ON DEMAND.",
        rule=rule,
    ).is_heading


def test_the_same_line_followed_by_its_own_peer_is_not_a_heading() -> None:
    """A heading with nothing under it heads nothing: it is a one-line clause."""
    score = heading_score("Entire Agreement", next_label=NEXT_PEER)

    assert not score.is_heading
    assert "followed_by_peer_label" in score.signals


def test_a_sentence_never_scores_as_a_heading() -> None:
    score = heading_score(
        "The Customer shall pay each invoice within thirty days.",
        next_label=NEXT_DEEPER,
    )

    assert score.score == 0.0
    assert score.signals == ("too_many_words",)


def test_terminal_punctuation_closes_the_gate() -> None:
    score = heading_score("Time is of the essence.", next_label=NEXT_DEEPER)

    assert score.score == 0.0
    assert score.signals == ("terminal_punctuation",)


def test_a_profile_can_loosen_the_terminal_punctuation_rule() -> None:
    rule = HeadingRule(forbid_terminal_punctuation=False)

    score = heading_score("Notices:", rule=rule, next_label=NEXT_DEEPER)

    assert score.signals == ("title_case", "short", "followed_by_deeper_label")
    assert score.is_heading


def test_a_profile_can_tighten_the_word_budget() -> None:
    rule = HeadingRule(max_words=2)

    assert not heading_score(
        "Limitation of Liability", rule=rule, next_label=NEXT_DEEPER
    ).is_heading
    assert heading_score("PAYMENT", rule=rule, next_label=NEXT_DEEPER).is_heading


def test_a_profile_can_refuse_all_caps_headings() -> None:
    rule = HeadingRule(allow_all_caps=False)

    score = heading_score("PAYMENT", rule=rule, next_label=NEXT_DEEPER)

    assert "all_caps" not in score.signals
    assert not score.is_heading


def test_multi_line_and_empty_text_are_gated() -> None:
    assert heading_score("PAYMENT\nTERMS").signals == ("multiline",)
    assert heading_score("   ").signals == ("empty",)


def test_a_lonely_heading_still_scores_but_lower() -> None:
    """Nothing labelled follows, so the strongest signal is missing."""
    lonely = heading_score("PAYMENT", next_label=NEXT_NONE)
    followed = heading_score("PAYMENT", next_label=NEXT_DEEPER)

    assert 0.0 < lonely.score < followed.score


def test_the_score_survives_the_verdict() -> None:
    """PRD section 6b: the score is kept rather than thresholded away."""
    score = heading_score("Entire Agreement", next_label=NEXT_PEER)

    assert score.score > 0.0
    assert not score.is_heading
    assert score.threshold == HEADING_THRESHOLD


def test_a_reader_may_move_the_threshold() -> None:
    assert heading_score(
        "Entire Agreement", next_label=NEXT_PEER, threshold=0.2
    ).is_heading


def test_heading_confidence_stays_inside_the_heuristic_band() -> None:
    assert heading_confidence(0.0) == 0.3
    assert heading_confidence(1.0) == 0.69
    assert heading_confidence(2.0) == 0.69
    assert HeadingScore(0.5, ()).confidence == heading_confidence(0.5)


def test_heading_resets_are_recognised_by_name(profile: Profile) -> None:
    assert heading_reset_name("SCHEDULE 1", profile=profile) == "schedule"
    assert heading_reset_name("Annex A", profile=profile) == "schedule"
    assert heading_reset_name("7.1 Payment", profile=profile) is None
    assert heading_reset_name("SCHEDULE 1", profile=None) is None


# --- stage 4: continuations ------------------------------------------------


def test_an_unlabelled_paragraph_continues_the_labelled_block_above_it() -> None:
    decision = continuation_for(open_label_level=2, heading=heading_score("A body."))

    assert decision.attaches
    assert decision.reason == "follows_label"
    assert 0.3 <= decision.confidence < 0.7


def test_an_indented_continuation_is_the_more_confident_one() -> None:
    indented = continuation_for(open_label_level=2, indent=4, label_indent=0)
    flush = continuation_for(open_label_level=2, indent=0, label_indent=0)

    assert indented.reason == "indented_under_label"
    assert indented.confidence > flush.confidence


def test_a_heading_claims_the_paragraph_before_a_continuation_can() -> None:
    decision = continuation_for(
        open_label_level=2, heading=heading_score("PAYMENT", next_label=NEXT_DEEPER)
    )

    assert not decision.attaches
    assert decision.reason == "heading_claims_it"
    assert decision.confidence == 0.0


def test_with_no_labelled_block_open_nothing_is_a_continuation() -> None:
    decision = continuation_for(open_label_level=None)

    assert not decision.attaches
    assert decision.reason == "no_open_label"
