"""Tests for the built-in structure profiles: generic, contract, markdown (issue #101).

These tests read the shipped YAML through the public API only -- no profile
is re-parsed by hand -- and they check the patterns against the exact label,
heading and span examples PRD § 6b lists, so a change to a pattern that
stops recognising one of them fails here rather than in a reader.
"""

from __future__ import annotations

import itertools
from importlib.resources import files
from pathlib import Path

import pytest

from redlines.blocks import RECOMMENDED_ROLES, RECOMMENDED_SPAN_TYPES
from redlines.profiles import (
    BUILTIN_PROFILE_NAMES,
    Profile,
    ProfileError,
    builtin_profile,
    parse_profile_yaml,
)

BUILTIN_DIR = Path(__file__).parent.parent / "redlines" / "profiles" / "builtin"

#: The rule lists a profile carries. `heading_rule` is deliberately absent:
#: it is one mapping of heuristics, not a list of rules.
RULE_LISTS = ("label_patterns", "heading_resets", "role_rules", "span_extractors")


# --- helpers ---------------------------------------------------------------
#
# The reader (#102) owns label extraction; these two helpers stand in for it
# so this file can assert what a profile's patterns actually do. They apply
# the documented conventions: label patterns are tried in order and the
# first match wins, with group 1 as the label where a pattern captures one;
# every span extractor runs and every match is kept.


def first_label(profile: Profile, text: str) -> tuple[str, str, str] | None:
    """Return ``(pattern name, label, remaining text)`` for the first pattern that matches."""
    for pattern in profile.label_patterns:
        match = pattern.compiled().match(text)
        if match is not None:
            label = match.group(1) if match.re.groups else match.group(0)
            return pattern.name, label, text[match.end() :]
    return None


def spans_of(profile: Profile, text: str) -> list[tuple[str, str]]:
    """Return every ``(type, span text)`` the profile's extractors find in ``text``."""
    return [
        (extractor.type, match.group(extractor.group))
        for extractor in profile.span_extractors
        for match in extractor.compiled().finditer(text)
    ]


def reset_names(profile: Profile, heading: str) -> list[str]:
    """Return the names of the heading resets that fire on ``heading``."""
    return [
        reset.name
        for reset in profile.heading_resets
        if reset.compiled().search(heading)
    ]


# --- every built-in loads, validates and is reachable by name --------------


@pytest.mark.parametrize("name", BUILTIN_PROFILE_NAMES)
def test_every_builtin_loads_and_validates(name: str) -> None:
    profile = builtin_profile(name)
    assert isinstance(profile, Profile)
    assert profile.description.strip(), f"{name} should say what it is for"


@pytest.mark.parametrize("name", BUILTIN_PROFILE_NAMES)
def test_builtin_name_matches_its_file_name(name: str) -> None:
    assert builtin_profile(name).name == name
    assert (BUILTIN_DIR / f"{name}.yaml").is_file()


def test_the_yaml_files_on_disk_are_exactly_the_declared_names() -> None:
    """No shipped-but-unlisted profile, and no listed-but-missing one."""
    on_disk = sorted(path.stem for path in BUILTIN_DIR.glob("*.yaml"))
    assert on_disk == sorted(BUILTIN_PROFILE_NAMES)


@pytest.mark.parametrize("name", BUILTIN_PROFILE_NAMES)
def test_builtin_ships_inside_the_installed_package(name: str) -> None:
    """Read through `importlib.resources`, the way `builtin_profile` does."""
    resource = files("redlines.profiles") / "builtin" / f"{name}.yaml"
    assert parse_profile_yaml(resource.read_text(encoding="utf-8")).name == name


@pytest.mark.parametrize("name", BUILTIN_PROFILE_NAMES)
def test_builtin_yaml_is_commented(name: str) -> None:
    """R1f: a built-in is also a worked example, so it explains its patterns."""
    text = (BUILTIN_DIR / f"{name}.yaml").read_text(encoding="utf-8")
    comment_lines = [
        line for line in text.splitlines() if line.lstrip().startswith("#")
    ]
    assert len(comment_lines) >= 20


def test_builtin_profile_is_cached() -> None:
    """A `Profile` is frozen, so every caller can share one object."""
    assert builtin_profile("contract") is builtin_profile("contract")


def test_unknown_builtin_name_is_rejected_and_names_the_alternatives() -> None:
    with pytest.raises(ProfileError) as excinfo:
        builtin_profile("legislation")
    message = str(excinfo.value)
    assert "legislation" in message
    for name in BUILTIN_PROFILE_NAMES:
        assert name in message


@pytest.mark.parametrize("name", BUILTIN_PROFILE_NAMES)
def test_builtin_roles_and_span_types_use_the_recommended_vocabulary(name: str) -> None:
    """The vocabulary is open (ADR-0005), but a built-in should not invent words."""
    profile = builtin_profile(name)
    for rule in profile.role_rules:
        assert rule.role in RECOMMENDED_ROLES
    for extractor in profile.span_extractors:
        assert extractor.type in RECOMMENDED_SPAN_TYPES


# --- contract: the labels PRD § 6b lists -----------------------------------

# (block text, the pattern expected to claim it, the label it should yield).
PRD_LABELS = [
    ("1.", "decimal", "1"),
    ("1.2", "decimal", "1.2"),
    ("1.2.3", "decimal", "1.2.3"),
    ("(a)", "alpha_paren", "a"),
    ("(i)", "alpha_paren", "i"),
    ("Article 5", "word_label", "Article 5"),
    ("Section 3", "word_label", "Section 3"),
    ("Schedule 2", "word_label", "Schedule 2"),
    ("§ 4", "section_symbol", "§ 4"),
    ("4.—(1)", "statute_subsection", "4.—(1)"),
]


@pytest.mark.parametrize(("text", "pattern_name", "label"), PRD_LABELS)
def test_contract_matches_the_prd_labels(
    text: str, pattern_name: str, label: str
) -> None:
    """Every label form PRD § 6b names is recognised, and yields the label as cited."""
    assert first_label(builtin_profile("contract"), text) == (pattern_name, label, "")


@pytest.mark.parametrize(("text", "pattern_name", "label"), PRD_LABELS)
def test_contract_labels_are_stripped_from_the_body_text(
    text: str, pattern_name: str, label: str
) -> None:
    """The same labels, followed by a clause: the separator is consumed with the label."""
    matched = first_label(
        builtin_profile("contract"), f"{text} The Supplier shall pay."
    )
    assert matched == (pattern_name, label, "The Supplier shall pay.")


@pytest.mark.parametrize(
    ("text", "pattern_name", "label", "style"),
    [
        ("(ii) the second item", "roman_paren", "ii", "roman"),
        ("(A) the first item", "alpha_paren", "A", "alpha"),
        ("A. Interpretation", "alpha_dot", "A", "alpha"),
        ("IV. Miscellaneous", "roman_dot", "IV", "roman"),
        ("Part IV", "word_label", "Part IV", "word"),
        ("Annex A", "word_label", "Annex A", "word"),
        ("§ 4.2 Payment", "section_symbol", "§ 4.2", "word"),
    ],
)
def test_contract_matches_the_neighbouring_label_forms(
    text: str, pattern_name: str, label: str, style: str
) -> None:
    contract = builtin_profile("contract")
    matched = first_label(contract, text)
    assert matched is not None
    assert (matched[0], matched[1]) == (pattern_name, label)
    by_name = {pattern.name: pattern for pattern in contract.label_patterns}
    assert by_name[pattern_name].style == style


def test_a_single_parenthesised_letter_is_alpha_by_design() -> None:
    """The PRD § 6b alpha/roman ambiguity, resolved in the profile.

    "(i)" is far more often the ninth item of an (a), (b), ... run than the
    first of a roman one, so single letters are claimed by ``alpha_paren``
    and only two-letter-or-longer forms reach ``roman_paren``. Which *depth*
    it lands at is still the reader's stack to resolve; the profile cannot
    express "ambiguous until you have seen the siblings".
    """
    contract = builtin_profile("contract")
    matched = first_label(contract, "(i) the ninth item")
    assert matched is not None and matched[0] == "alpha_paren"
    by_name = {pattern.name: pattern for pattern in contract.label_patterns}
    assert by_name["alpha_paren"].style == "alpha"
    assert by_name["alpha_paren"].depth_mode == "stack"
    assert by_name["decimal"].depth_mode == "arithmetic"


def test_contract_does_not_label_ordinary_prose() -> None:
    assert (
        first_label(builtin_profile("contract"), "The Supplier shall deliver.") is None
    )


def test_a_year_at_the_start_of_a_paragraph_is_mislabelled() -> None:
    """A known and accepted limit, documented rather than papered over.

    The format has no sequence awareness (ADR-0028 Consequences), so a
    paragraph opening "2019 saw..." matches the decimal pattern. Scoring it
    against the numbering run belongs to the reader (#102), which reports
    the doubt through ``matched_by`` and ``confidence`` (ADR-0030).
    """
    matched = first_label(builtin_profile("contract"), "2019 saw the parties agree.")
    assert matched is not None and matched[1] == "2019"


# --- contract: heading resets ----------------------------------------------


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        ("Schedule 1", "schedule"),
        ("SCHEDULE 1", "schedule"),
        ("Annex A", "schedule"),
        ("Appendix 2", "schedule"),
        ("Part IV", "part"),
    ],
)
def test_contract_heading_resets_fire_on_the_numbering_boundaries(
    heading: str, expected: str
) -> None:
    assert reset_names(builtin_profile("contract"), heading) == [expected]


@pytest.mark.parametrize("name", ["contract", "markdown"])
def test_attachment_is_a_schedule_everywhere_it_is_recognised(name: str) -> None:
    """ "Attachment 3" is a label and a numbering reset, so it is a schedule too.

    A profile that opens a new numbering section at "Attachment 3" but never
    gives it ``role='schedule'`` -- nor reads "in Attachment 3" as a
    cross-reference -- would contradict itself, so the four lists that name
    the schedule words are checked together.
    """
    profile = builtin_profile(name)
    assert first_label(profile, "Attachment 3") == ("word_label", "Attachment 3", "")
    assert reset_names(profile, "Attachment 3") == ["schedule"]
    roles = {
        rule.role
        for rule in profile.role_rules
        if rule.match in ("heading", "ancestor_heading")
        and rule.compiled().search("Attachment 3")
    }
    assert roles == {"schedule"}
    assert ("cross_reference", "Attachment 3") in spans_of(
        profile, "as set out in Attachment 3 to this agreement"
    )


@pytest.mark.parametrize(
    "heading", ["Particulars", "Parties", "Termination", "Payment"]
)
def test_contract_heading_resets_leave_ordinary_headings_alone(heading: str) -> None:
    """A reset clears the numbering stack, so a false positive is expensive."""
    assert reset_names(builtin_profile("contract"), heading) == []


# --- contract: spans -------------------------------------------------------


def test_contract_finds_a_defined_term() -> None:
    text = '"Confidential Information" means information disclosed by a party.'
    assert ("defined_term", "Confidential Information") in spans_of(
        builtin_profile("contract"), text
    )


def test_contract_finds_a_defined_term_with_curly_quotes() -> None:
    text = "“Confidential Information” means information."
    assert ("defined_term", "Confidential Information") in spans_of(
        builtin_profile("contract"), text
    )


def test_contract_finds_a_cross_reference() -> None:
    """Group 1 is the bare label, which is what a renumbering check needs."""
    found = spans_of(
        builtin_profile("contract"), "Subject to clause 7.2, the fee is due."
    )
    assert ("cross_reference", "7.2") in found


def test_contract_finds_both_references_in_an_enumeration() -> None:
    """ "Clauses 7.2 and 7.3" needs a second extractor; two may share a type."""
    found = spans_of(
        builtin_profile("contract"), "Clauses 7.2 and 7.3 survive termination."
    )
    references = [value for span_type, value in found if span_type == "cross_reference"]
    assert references == ["7.2", "7.3"]


def test_a_third_reference_in_one_enumeration_is_not_reached() -> None:
    """The limit of what the format can express, recorded here on purpose.

    Extractors are independent regexes with no repetition and no sequence
    awareness (ADR-0028 Consequences), so the pattern that reaches the
    second reference in "Clauses 7.2 and 7.3" cannot reach the third in
    "Clauses 7.2, 7.3 and 7.4". Closing this needs either a repeat-group
    capability in the format or list handling in the semantic pass (#104).
    """
    found = spans_of(
        builtin_profile("contract"), "Clauses 7.2, 7.3 and 7.4 survive termination."
    )
    references = [value for span_type, value in found if span_type == "cross_reference"]
    assert "7.2" in references and "7.3" in references
    assert "7.4" not in references


def test_contract_finds_a_cross_reference_to_a_word_labelled_part() -> None:
    found = spans_of(
        builtin_profile("contract"), "as set out in Schedule 2 to this deed"
    )
    assert ("cross_reference", "Schedule 2") in found


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("This Agreement is dated 1 January 2026.", "1 January 2026"),
        ("Signed this 1st day of January 2026.", "1st day of January 2026"),
        ("Effective from January 1, 2026.", "January 1, 2026"),
        ("Effective from 2026-01-31.", "2026-01-31"),
    ],
)
def test_contract_finds_a_date(text: str, expected: str) -> None:
    assert ("date", expected) in spans_of(builtin_profile("contract"), text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("The fee is USD 5,000.00 per month.", "USD 5,000.00"),
        ("The cap is US$1,000,000.", "US$1,000,000"),
        ("A deposit of $1,500 is payable.", "$1,500"),
        ("A deposit of S$250 is payable.", "S$250"),
    ],
)
def test_contract_finds_an_amount(text: str, expected: str) -> None:
    assert ("amount", expected) in spans_of(builtin_profile("contract"), text)


def test_contract_finds_the_parties() -> None:
    text = 'Acme Widgets Pte Ltd (the "Supplier") shall invoice the Customer monthly.'
    found = spans_of(builtin_profile("contract"), text)
    assert ("party", "Supplier") in found
    assert ("party", "Customer") in found


# --- contract: roles -------------------------------------------------------


def test_contract_role_rules_cover_the_sections_the_prd_names() -> None:
    roles = [rule.role for rule in builtin_profile("contract").role_rules]
    assert set(roles) == {
        "definitions",
        "definition",
        "recital",
        "schedule",
        "signature",
    }


def test_definitions_rule_precedes_the_rule_that_builds_on_it() -> None:
    """`parent_role` reads a role another rule assigned, so order is load-bearing."""
    rules = builtin_profile("contract").role_rules
    names = [(rule.role, rule.match) for rule in rules]
    assert names.index(("definitions", "heading")) < names.index(
        ("definition", "parent_role")
    )


@pytest.mark.parametrize(
    ("heading", "role"),
    [
        ("Definitions", "definitions"),
        ("1. Definitions and Interpretation", "definitions"),
        ("Background", "recital"),
        ("Schedule 1", "schedule"),
        ("IN WITNESS WHEREOF", "signature"),
    ],
)
def test_contract_heading_role_rules_match_their_headings(
    heading: str, role: str
) -> None:
    """Heading patterns are matched with any label already stripped."""
    text = heading.split(". ", 1)[-1]
    matched = [
        rule.role
        for rule in builtin_profile("contract").role_rules
        if rule.match == "heading" and rule.compiled().search(text)
    ]
    assert matched[:1] == [role]


# --- generic ---------------------------------------------------------------


def test_generic_declares_no_labels_and_no_roles() -> None:
    """PRD D30's degrade path: one block per paragraph, alignment still working."""
    generic = builtin_profile("generic")
    assert generic.label_patterns == ()
    assert generic.role_rules == ()
    assert generic.heading_resets == ()


def test_generic_keeps_only_the_format_independent_spans() -> None:
    generic = builtin_profile("generic")
    assert {extractor.type for extractor in generic.span_extractors} == {
        "date",
        "amount",
    }
    found = spans_of(generic, "An invoice for USD 5,000.00 is due on 1 January 2026.")
    assert ("amount", "USD 5,000.00") in found
    assert ("date", "1 January 2026") in found


def test_generic_does_not_guess_at_contract_conventions() -> None:
    text = 'Subject to clause 7.2, "Confidential Information" means information.'
    assert spans_of(builtin_profile("generic"), text) == []


# --- markdown --------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "pattern_name", "label"),
    [
        entry
        for entry in PRD_LABELS
        if entry[1] not in ("section_symbol", "statute_subsection")
    ],
)
def test_markdown_matches_the_same_labels_as_contract(
    text: str, pattern_name: str, label: str
) -> None:
    """A markdown contract gets the same labels as its plain-text twin (PRD § 6b)."""
    assert first_label(builtin_profile("markdown"), text) == (pattern_name, label, "")


@pytest.mark.parametrize("text", ["§ 4", "4.—(1)"])
def test_markdown_leaves_the_statute_label_forms_to_the_legislation_profile(
    text: str,
) -> None:
    """A deliberate difference from `contract`, not an oversight: those forms are
    a plain-text statute idiom, and the `legislation` profile is 1.1 (PRD R1d)."""
    assert first_label(builtin_profile("markdown"), text) is None


def test_the_statute_forms_are_the_only_labels_markdown_drops() -> None:
    """The parity claim in markdown.yaml's header, asserted rather than trusted.

    Every label pattern `contract` carries is also in `markdown` except the
    two statute idioms the test above pins, so a third silent omission --
    `roman_dot` was one -- fails here.
    """
    contract_names = [
        pattern.name for pattern in builtin_profile("contract").label_patterns
    ]
    markdown_names = [
        pattern.name for pattern in builtin_profile("markdown").label_patterns
    ]
    assert [name for name in contract_names if name not in markdown_names] == [
        "statute_subsection",
        "section_symbol",
    ]
    # Order is load-bearing (first match wins), so the shared names keep it.
    assert markdown_names == [name for name in contract_names if name in markdown_names]


def test_markdown_reads_a_roman_heading_the_way_contract_does() -> None:
    """`## IV. Miscellaneous` in a document migrated from plain text."""
    assert first_label(builtin_profile("markdown"), "IV. Miscellaneous") == (
        "roman_dot",
        "IV",
        "Miscellaneous",
    )


def test_markdown_does_not_score_all_caps_lines_as_headings() -> None:
    """Headings come from the `#`s; an upper-case line in markdown is emphasis."""
    assert builtin_profile("markdown").heading_rule.allow_all_caps is False
    assert builtin_profile("contract").heading_rule.allow_all_caps is True


def test_markdown_resets_numbering_at_a_schedule() -> None:
    assert reset_names(builtin_profile("markdown"), "Schedule 1") == ["schedule"]


def test_markdown_adds_the_note_role() -> None:
    """The one role `contract` does not carry: markdown is the drafting format."""
    contract_roles = {rule.role for rule in builtin_profile("contract").role_rules}
    markdown_roles = {rule.role for rule in builtin_profile("markdown").role_rules}
    assert markdown_roles - contract_roles == {"note"}


def test_markdown_finds_the_same_semantics_as_contract() -> None:
    text = 'Under clause 7.2, "Fees" means USD 5,000.00 payable on 1 January 2026.'
    found = spans_of(builtin_profile("markdown"), text)
    assert ("cross_reference", "7.2") in found
    assert ("defined_term", "Fees") in found
    assert ("amount", "USD 5,000.00") in found
    assert ("date", "1 January 2026") in found


def test_markdown_leaves_emphasis_to_the_reader() -> None:
    """`**bold**` is syntax the reader strips, so no extractor here looks for it."""
    assert all(
        extractor.type != "emphasis"
        for extractor in builtin_profile("markdown").span_extractors
    )


# --- drift: how much the three files repeat each other ---------------------
#
# ADR-0028 deliberately ships no composition mechanism (no `extends:`) and
# names #101 as the point where real duplication between profiles would
# first show up: "if two of the three share most of their span_extractors
# verbatim, that is the evidence for adding composition -- not before."
# These two tests keep that evidence visible and current.


def test_no_two_builtins_share_a_verbatim_identical_rule_list() -> None:
    """Whole-list duplication would mean one profile is the other, renamed."""
    for first, second in itertools.combinations(BUILTIN_PROFILE_NAMES, 2):
        left, right = builtin_profile(first), builtin_profile(second)
        for field in RULE_LISTS:
            left_rules = getattr(left, field)
            right_rules = getattr(right, field)
            if not left_rules or not right_rules:
                continue
            assert left_rules != right_rules, (
                f"{first} and {second} have identical {field}; "
                "re-read ADR-0028's revisit condition on composition"
            )


#: Rules that are byte-for-byte the same record in both profiles, as of #101.
#: Kept as a snapshot so the overlap cannot grow unnoticed: raising a number
#: here is a deliberate decision to repeat a rule, and pushing one to equal
#: the whole list is the composition evidence ADR-0028 asks for.
VERBATIM_OVERLAP = {
    ("generic", "contract"): {
        "label_patterns": 0,
        "heading_resets": 0,
        "role_rules": 0,
        "span_extractors": 4,
    },
    ("generic", "markdown"): {
        "label_patterns": 0,
        "heading_resets": 0,
        "role_rules": 0,
        "span_extractors": 4,
    },
    ("contract", "markdown"): {
        "label_patterns": 6,
        "heading_resets": 1,
        "role_rules": 6,
        "span_extractors": 10,
    },
}


@pytest.mark.parametrize(("pair", "expected"), sorted(VERBATIM_OVERLAP.items()))
def test_verbatim_rule_overlap_is_the_documented_snapshot(
    pair: tuple[str, str], expected: dict[str, int]
) -> None:
    left, right = builtin_profile(pair[0]), builtin_profile(pair[1])
    counted = {
        field: len(
            [rule for rule in getattr(left, field) if rule in getattr(right, field)]
        )
        for field in RULE_LISTS
    }
    assert counted == expected


@pytest.mark.parametrize(("pair", "expected"), sorted(VERBATIM_OVERLAP.items()))
def test_every_rule_list_keeps_something_of_its_own(
    pair: tuple[str, str], expected: dict[str, int]
) -> None:
    """The longer of any two non-empty lists still holds a rule the other lacks.

    The shorter one may be a strict subset -- `generic`'s spans are a
    deliberate subset of `contract`'s, and `markdown`'s extractors are
    `contract`'s minus the curly-quote variant -- but total repetition in
    both directions would make one profile the other under a new name.
    """
    left, right = builtin_profile(pair[0]), builtin_profile(pair[1])
    for field in RULE_LISTS:
        left_rules = getattr(left, field)
        right_rules = getattr(right, field)
        if not left_rules or not right_rules:
            continue
        shared = expected[field]
        assert shared < max(len(left_rules), len(right_rules))
