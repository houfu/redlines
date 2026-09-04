"""Tests for the semantic pass: roles, spans and PRD § 6b's definitions (#104).

The pass is driven by a profile, so most of these run the shipped ``contract``
profile over the plain-text reader's output for one small agreement, which is
the pairing the milestone actually ships. The rest are the questions a profile
cannot answer on its own: what "under a heading" means on two different tree
shapes, which of two matching ancestors decides, what happens when two
extractors overlap, and whether running the pass twice does anything the
second time.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from redlines.blocks import Block, BlockKind, BlockTree, Span
from redlines.profiles import Profile, builtin_profile, profile_from_mapping
from redlines.readers.markdown import MarkdownReader
from redlines.readers.text import PlainTextReader
from redlines.semantic import (
    DEFINITION_ROLE,
    DEFINITIONS_ROLE,
    ancestor_headings,
    apply_semantics,
    extract_spans,
    heading_line,
)

HARD_CASES = Path(__file__).parent / "corpus" / "hard_cases"

CONTRACT = """\
MASTER SERVICES AGREEMENT

This agreement is made on 1 January 2026 between Acme Analytics Ltd (the
"Supplier") and Beta Retail plc (the "Customer").

RECITALS

A. The Supplier provides data analytics services.

B. The Customer wishes to receive those services.

1. DEFINITIONS

1.1 "Agreement" means this agreement and its schedules.

1.2 "Charges" means the fees set out in Schedule 2, being USD 5,000.00 per month.

7. TERMINATION

7.1 Either party may terminate this agreement on thirty days' notice.

7.2 The Customer shall pay all Charges due under clause 7.1 on termination.

SIGNATURES

Signed for and on behalf of Acme Analytics Ltd.

SCHEDULE 1

1. The Services comprise hosting and support.
"""


# --- helpers ---------------------------------------------------------------


@pytest.fixture
def contract() -> Profile:
    """The shipped ``contract`` profile: the default for plain text."""
    return builtin_profile("contract")


@pytest.fixture
def agreement(contract: Profile) -> BlockTree:
    """`CONTRACT`, read by the plain-text reader and put through the pass."""
    return apply_semantics(PlainTextReader().read(CONTRACT, profile=contract), contract)


def read(text: str, profile: Profile) -> BlockTree:
    """Read ``text`` under ``profile`` and apply the semantic pass to it."""
    return apply_semantics(PlainTextReader().read(text, profile=profile), profile)


def one(tree: BlockTree, label: str) -> Block:
    """Return the single block carrying ``label``, failing loudly otherwise."""
    found = [block for block in tree.walk() if block.label == label]
    assert len(found) == 1, f"expected one block labelled {label!r}, got {len(found)}"
    return found[0]


def texted(tree: BlockTree, text: str) -> Block:
    """Return the single block whose text is exactly ``text``."""
    found = [block for block in tree.walk() if block.text == text]
    assert len(found) == 1, f"expected one block reading {text!r}, got {len(found)}"
    return found[0]


def span_texts(block: Block, type_: str) -> list[str]:
    """Return the text each span of ``type_`` covers, in the order they are held."""
    return [
        block.text[span.start : span.end] for span in block.spans if span.type == type_
    ]


def roles(tree: BlockTree) -> list[tuple[str | None, str | None]]:
    """Return ``(label or text, role)`` for every block that carries text or a label.

    Container blocks are left out, which is what lets two readers with
    different container conventions be compared at all.
    """
    return [
        (block.label or block.text, block.role)
        for block in tree.walk()
        if block.kind not in (BlockKind.DOCUMENT, BlockKind.SECTION)
    ]


def block(kind: BlockKind, **fields: object) -> Block:
    """Build a block, defaulting ``matched_by`` so a hand-built tree is honest."""
    fields.setdefault("matched_by", "test")
    fields.setdefault("confidence", 1.0)
    return Block(kind=kind, **fields)  # type: ignore[arg-type]


# --- the contract profile over the text reader -----------------------------


def test_the_definitions_section_and_its_definitions_are_recognised(
    agreement: BlockTree,
) -> None:
    """PRD § 6b: the section gets `definitions`, its children `definition`."""
    heading = texted(agreement, "DEFINITIONS")
    first = one(agreement, "1.1")
    second = one(agreement, "1.2")

    assert heading.kind is BlockKind.HEADING
    assert heading.role == DEFINITIONS_ROLE
    assert first.role == second.role == DEFINITION_ROLE
    assert span_texts(first, "defined_term") == ["Agreement"]
    assert span_texts(second, "defined_term") == ["Charges"]


def test_the_definitions_section_block_carries_the_role_too(
    agreement: BlockTree,
) -> None:
    """The section a definitions heading opens is what PRD § 6b names, and the
    profile format has no way to say so (ADR-0028): the pass fills it in."""
    sections = [
        found
        for found in agreement.walk()
        if found.kind is BlockKind.SECTION and found.role == DEFINITIONS_ROLE
    ]

    assert len(sections) == 1
    assert sections[0].children[0].text == "DEFINITIONS"
    assert sections[0].attrs["semantic"]["role_match"] == "definitions_heading"


def test_a_schedule_roles_its_heading_and_everything_under_it(
    agreement: BlockTree,
) -> None:
    """Two rules, two landing places -- and a heading that is all label."""
    heading = one(agreement, "SCHEDULE 1")
    clause = texted(agreement, "The Services comprise hosting and support.")

    assert heading.kind is BlockKind.HEADING
    assert heading.text == ""
    assert heading.role == "schedule"
    # Its text is empty, so the pattern reached it through the heading as
    # written -- the label and the text rejoined.
    assert heading.attrs["semantic"]["matched"] == "heading_line"
    assert heading_line(heading) == "SCHEDULE 1"
    assert clause.role == "schedule"
    assert clause.attrs["semantic"]["role_match"] == "ancestor_heading"
    assert clause.attrs["semantic"]["ancestor"] == "SCHEDULE 1"


def test_a_definitions_section_inside_a_schedule_still_yields_definitions(
    contract: Profile,
) -> None:
    """What `contract.yaml` says its rule order is for, asserted end to end.

    The nearer evidence -- this section's own heading -- beats the schedule
    heading two steps out, and the clauses that are not definitions still come
    out `schedule`.
    """
    source = (
        "SCHEDULE 2\n"
        "\n"
        "1. DEFINITIONS\n"
        "\n"
        '1.1 "Support Hours" means 9am to 5pm.\n'
        "\n"
        "2. SERVICE LEVELS\n"
        "\n"
        "2.1 The Supplier shall meet the Uptime target.\n"
    )

    tree = read(source, contract)

    assert texted(tree, "DEFINITIONS").role == DEFINITIONS_ROLE
    assert one(tree, "1.1").role == DEFINITION_ROLE
    assert texted(tree, "SERVICE LEVELS").role == "schedule"
    assert one(tree, "2.1").role == "schedule"


def test_recital_and_signature_headings_carry_their_roles(
    agreement: BlockTree,
) -> None:
    assert texted(agreement, "RECITALS").role == "recital"
    assert texted(agreement, "SIGNATURES").role == "signature"
    # `contract` writes both as `heading` rules, so they land on the heading
    # and not on what follows it. That is the profile's choice, not the pass's.
    assert (
        texted(agreement, "The Supplier provides data analytics services.").role is None
    )


def test_a_cross_reference_carries_the_label_it_refers_to(
    agreement: BlockTree,
) -> None:
    """R1c: "cross-reference updated to follow renumbering", not "text changed"."""
    clause = one(agreement, "7.2")

    references = [span for span in clause.spans if span.type == "cross_reference"]
    assert [span.value for span in references] == ["7.1"]
    assert [clause.text[span.start : span.end] for span in references] == ["7.1"]


def test_a_cross_reference_label_is_normalised_the_way_a_label_is(
    contract: Profile,
) -> None:
    """Whitespace collapsed, one trailing full stop dropped."""
    spans = extract_spans(
        "The Supplier shall comply with clause 7.2. and Schedule 2.", profile=contract
    )

    assert [span.value for span in spans if span.type == "cross_reference"] == [
        "7.2",
        "Schedule 2",
    ]


def test_parties_dates_and_amounts_are_found(agreement: BlockTree) -> None:
    recital = texted(
        agreement,
        "This agreement is made on 1 January 2026 between Acme Analytics Ltd "
        '(the "Supplier") and Beta Retail plc (the "Customer").',
    )
    charges = one(agreement, "1.2")

    assert span_texts(recital, "party") == ["Supplier", "Customer"]
    assert span_texts(recital, "date") == ["1 January 2026"]
    assert span_texts(charges, "amount") == ["USD 5,000.00"]


def test_every_span_lies_inside_the_text_it_describes(agreement: BlockTree) -> None:
    """The `Block` check this issue added, asserted over a real document."""
    for found in agreement.walk():
        for span in found.spans:
            assert 0 <= span.start < span.end <= len(found.text)


def test_a_span_that_runs_past_its_block_is_rejected() -> None:
    with pytest.raises(ValueError, match="past the end"):
        Block(
            kind=BlockKind.PARAGRAPH,
            text="1 January",
            spans=(Span(type="date", start=0, end=14),),
        )


# --- PRD § 6b: definitions as a run-on paragraph ---------------------------


def test_definitions_written_as_one_run_on_paragraph_keep_every_term(
    contract: Profile,
) -> None:
    """The § 6b hard case the reader is right to leave alone.

    `tests/test_text_reader.py` marks this xfail for the *reader*: five
    mechanical stages see one labelled paragraph and say so. The semantic pass
    is where the four definitions inside it become visible, as four
    `defined_term` spans on the one block rather than four blocks.
    """
    source = (HARD_CASES / "definitions_run_on.txt").read_text(encoding="utf-8")

    tree = read(source, contract)
    clause = one(tree, "1.1")

    assert clause.role == DEFINITION_ROLE
    assert span_texts(clause, "defined_term") == [
        "Agreement",
        "Business Day",
        "Charges",
        "Services",
    ]
    assert clause.attrs["semantic"]["defined_terms"] == 4


def test_a_cross_reference_in_prose_is_still_not_resolved(contract: Profile) -> None:
    """The other § 6b hard case the pass does *not* close, said out loud.

    "Clause 4.1" is a span with a value; "the preceding sub-clause" is not,
    because a span extractor is a regex over one block's text and has no way
    to count backwards through the numbering. That stays xfail in
    `tests/test_text_reader.py` and it stays true here.
    """
    source = (HARD_CASES / "cross_references_in_prose.txt").read_text(encoding="utf-8")

    tree = read(source, contract)

    assert one(tree, "4.2").spans == ()
    assert [
        span.value for span in one(tree, "4.4").spans if span.type == "cross_reference"
    ] == ["4.1", "9"]


def test_a_glossary_is_recognised_from_the_shape_of_its_members(
    contract: Profile,
) -> None:
    """The second path: no heading the profile knows, but the members read
    like definitions -- *quoted term, "means", text* -- so they are."""
    source = (
        "GLOSSARY OF TERMS\n"
        "\n"
        '"Agreement" means this agreement and its schedules.\n'
        "\n"
        '"Charges" means the fees payable by the Customer.\n'
        "\n"
        "The parties may agree further terms in writing.\n"
    )

    tree = read(source, contract)
    heading = texted(tree, "GLOSSARY OF TERMS")
    first = texted(tree, '"Agreement" means this agreement and its schedules.')
    prose = texted(tree, "The parties may agree further terms in writing.")

    # No profile rule names this heading; the shape of what follows it does.
    assert heading.role == DEFINITIONS_ROLE
    assert heading.attrs["semantic"]["role_match"] == "definitions_shape"
    assert first.role == DEFINITION_ROLE
    # "Mostly", not "only": the odd paragraph among them comes along.
    assert prose.role == DEFINITION_ROLE


def test_one_paragraph_holding_two_definitions_is_a_definitions_section(
    contract: Profile,
) -> None:
    """A lone run-on member counts as the shape only when it holds two or more."""
    run_on = (
        "GLOSSARY OF TERMS\n"
        "\n"
        '"Agreement" means this agreement; "Charges" means the fees payable.\n'
    )
    single = 'GLOSSARY OF TERMS\n\n"Agreement" means this agreement.\n'

    assert (
        texted(read(run_on, contract), run_on.splitlines()[2]).role == DEFINITION_ROLE
    )
    assert texted(read(single, contract), single.splitlines()[2]).role is None


def test_a_profile_that_never_names_the_role_gets_no_definitions(
    contract: Profile,
) -> None:
    """The heuristic is gated on the profile asking for it, not on the text."""
    source = (
        "GLOSSARY OF TERMS\n"
        "\n"
        '"Agreement" means this agreement and its schedules.\n'
        "\n"
        '"Charges" means the fees payable by the Customer.\n'
    )

    generic = read(source, builtin_profile("generic"))

    assert {found.role for found in generic.walk()} == {None}
    # The same text under `contract`, which does name the role, does get it.
    assert (
        texted(
            read(source, contract), '"Charges" means the fees payable by the Customer.'
        ).role
        == DEFINITION_ROLE
    )


# --- what "under a heading" means ------------------------------------------


def section_shaped() -> BlockTree:
    """A tree shaped the way `PlainTextReader` shapes one: a section per heading."""
    return BlockTree.build(
        block(
            BlockKind.DOCUMENT,
            children=(
                block(
                    BlockKind.SECTION,
                    children=(
                        block(BlockKind.HEADING, text="Definitions", level=1),
                        block(
                            BlockKind.LIST_ITEM,
                            text='"Charges" means the fees payable.',
                            label="1.1",
                            level=2,
                        ),
                    ),
                ),
                block(
                    BlockKind.SECTION,
                    children=(
                        block(BlockKind.HEADING, text="Schedule 1", level=1),
                        block(
                            BlockKind.LIST_ITEM,
                            text="The Services comprise hosting.",
                            label="1",
                            level=2,
                        ),
                    ),
                ),
            ),
        )
    )


def flat_shaped() -> BlockTree:
    """The same document from a reader that emits no containers at all."""
    return BlockTree.build(
        block(
            BlockKind.DOCUMENT,
            children=(
                block(BlockKind.HEADING, text="Definitions", level=1),
                block(
                    BlockKind.LIST_ITEM,
                    text='"Charges" means the fees payable.',
                    label="1.1",
                    level=2,
                ),
                block(BlockKind.HEADING, text="Schedule 1", level=1),
                block(
                    BlockKind.LIST_ITEM,
                    text="The Services comprise hosting.",
                    label="1",
                    level=2,
                ),
            ),
        )
    )


@pytest.mark.parametrize("build", [section_shaped, flat_shaped])
def test_under_a_heading_means_the_same_on_both_tree_shapes(
    build: object, contract: Profile
) -> None:
    """A section whose first child is the heading, or a run of sibling headings."""
    tree = apply_semantics(build(), contract)  # type: ignore[operator]

    assert roles(tree) == [
        ("Definitions", DEFINITIONS_ROLE),
        ("1.1", DEFINITION_ROLE),
        ("Schedule 1", "schedule"),
        ("1", "schedule"),
    ]


def test_ancestor_headings_are_reported_nearest_first_on_a_flat_tree() -> None:
    """A flat run of headings nests by ``level``: the deeper one is nearer."""
    tree = BlockTree.build(
        block(
            BlockKind.DOCUMENT,
            children=(
                block(BlockKind.HEADING, text="Part One", level=1),
                block(BlockKind.HEADING, text="Charges", level=2),
                block(BlockKind.PARAGRAPH, text="The Customer shall pay."),
                block(BlockKind.HEADING, text="Term", level=2),
                block(BlockKind.PARAGRAPH, text="This agreement runs for a year."),
            ),
        )
    )

    paragraph = tree.block_at("/paragraph[1]")
    assert [found.text for found in ancestor_headings(tree.root, paragraph.path)] == [
        "Charges",
        "Part One",
    ]
    # A heading is never under a heading of its own level.
    assert [found.text for found in ancestor_headings(tree.root, "/heading[3]")] == [
        "Part One"
    ]
    assert ancestor_headings(tree.root, "/heading[1]") == ()


def test_ancestor_headings_on_the_section_shape_walk_out_of_the_sections() -> None:
    tree = apply_semantics(section_shaped(), builtin_profile("contract"))
    item = tree.block_at("/section[2]/list_item[1]")

    assert [found.text for found in ancestor_headings(tree.root, item.path)] == [
        "Schedule 1"
    ]


def test_a_heading_that_holds_its_own_content_is_an_ancestor_of_it(
    contract: Profile,
) -> None:
    """The third shape: a reader that nests content inside the heading block."""
    tree = BlockTree.build(
        block(
            BlockKind.DOCUMENT,
            children=(
                block(
                    BlockKind.HEADING,
                    text="Schedule 1",
                    level=1,
                    children=(
                        block(BlockKind.PARAGRAPH, text="The Services are hosted."),
                    ),
                ),
            ),
        )
    )

    applied = apply_semantics(tree, contract)
    paragraph = applied.block_at("/heading[1]/paragraph[1]")

    assert [
        found.text for found in ancestor_headings(applied.root, paragraph.path)
    ] == ["Schedule 1"]
    assert paragraph.role == "schedule"


# --- proximity, parent_role and rule order ---------------------------------


NESTED = profile_from_mapping(
    {
        "name": "nested-headings",
        "role_rules": [
            # Deliberately the "wrong" way round: the outer heading's rule is
            # listed first, so list order alone would give it the paragraph.
            {
                "role": "decision",
                "match": "ancestor_heading",
                "pattern": "^My decision",
            },
            {
                "role": "conclusion",
                "match": "ancestor_heading",
                "pattern": "^Conclusion",
            },
        ],
    }
)


def test_the_nearest_ancestor_heading_decides_however_the_rules_are_ordered() -> None:
    """ADR-0028's example: a "Conclusion" nested inside "My decision"."""
    tree = BlockTree.build(
        block(
            BlockKind.DOCUMENT,
            children=(
                block(
                    BlockKind.SECTION,
                    children=(
                        block(BlockKind.HEADING, text="My decision", level=1),
                        block(BlockKind.PARAGRAPH, text="I have decided."),
                        block(
                            BlockKind.SECTION,
                            children=(
                                block(BlockKind.HEADING, text="Conclusion", level=2),
                                block(BlockKind.PARAGRAPH, text="So I conclude."),
                            ),
                        ),
                    ),
                ),
            ),
        )
    )

    applied = apply_semantics(tree, NESTED)

    assert texted(applied, "So I conclude.").role == "conclusion"
    assert texted(applied, "I have decided.").role == "decision"
    inner = texted(applied, "So I conclude.")
    assert inner.attrs["semantic"]["ancestor"] == "Conclusion"
    assert inner.attrs["semantic"]["role_rule"] == 1


def test_the_nearest_ancestor_decides_on_a_flat_run_of_headings_too() -> None:
    """The same, on the shape a reader that emits no containers produces.

    `ancestor_headings` reports ``B`` as the nearer of the two, so the rule
    matching ``B`` must win however the two are listed -- one container step
    can contribute several headings and they are not all the same distance
    away.
    """
    flat = BlockTree.build(
        block(
            BlockKind.DOCUMENT,
            children=(
                block(BlockKind.HEADING, text="My decision", level=1),
                block(BlockKind.HEADING, text="Conclusion", level=2),
                block(BlockKind.PARAGRAPH, text="So I conclude."),
            ),
        )
    )
    assert [found.text for found in ancestor_headings(flat.root, "/paragraph[1]")] == [
        "Conclusion",
        "My decision",
    ]

    applied = apply_semantics(flat, NESTED)

    paragraph = texted(applied, "So I conclude.")
    assert paragraph.role == "conclusion"
    assert paragraph.attrs["semantic"]["ancestor"] == "Conclusion"


def test_list_order_breaks_a_tie_between_rules_matching_the_same_heading() -> None:
    """Proximity first; where two rules match one heading, the profile decides."""
    profile = profile_from_mapping(
        {
            "name": "tied",
            "role_rules": [
                {"role": "first", "match": "ancestor_heading", "pattern": "^Sched"},
                {"role": "second", "match": "ancestor_heading", "pattern": "^Schedule"},
            ],
        }
    )
    tree = BlockTree.build(
        block(
            BlockKind.DOCUMENT,
            children=(
                block(BlockKind.HEADING, text="Schedule 1", level=1),
                block(BlockKind.PARAGRAPH, text="The Services are hosted."),
            ),
        )
    )

    applied = apply_semantics(tree, profile)

    assert texted(applied, "The Services are hosted.").role == "first"


def test_parent_role_sees_the_role_its_parent_was_given_this_pass() -> None:
    """Roles are assigned top-down, which is the whole point of the rule."""
    profile = profile_from_mapping(
        {
            "name": "parented",
            "role_rules": [
                # The more specific rule first: the ancestor rule below also
                # matches the continuation block, and the first match wins.
                {"role": "annex_item", "match": "parent_role", "parent_role": "annex"},
                {"role": "annex", "match": "ancestor_heading", "pattern": "^Annex"},
            ],
        }
    )
    tree = BlockTree.build(
        block(
            BlockKind.DOCUMENT,
            children=(
                block(BlockKind.HEADING, text="Annex A", level=1),
                block(
                    BlockKind.LIST_ITEM,
                    text="The first item.",
                    label="1",
                    children=(block(BlockKind.PARAGRAPH, text="Its continuation."),),
                ),
            ),
        )
    )

    applied = apply_semantics(tree, profile)

    assert texted(applied, "The first item.").role == "annex"
    child = texted(applied, "Its continuation.")
    assert child.role == "annex_item"
    assert child.attrs["semantic"]["role_match"] == "parent_role"


ORDERED = [
    {"role": "body", "match": "ancestor_heading", "pattern": "^Schedule"},
    {"role": "schedule", "match": "heading", "pattern": "^Schedule"},
]


def test_list_order_is_precedence_across_the_three_match_kinds() -> None:
    """ADR-0028's "tried in order and the first match wins", the whole rule.

    Proximity is the *one* exception and it is scoped to ``ancestor_heading``
    (ADR-0028's Decision; the schema's ``role_rules`` description). It does not
    reach across kinds: the inner heading below is under the outer one *and* is
    itself a heading, and which of the two rules decides is whichever the
    profile lists first -- otherwise an author could not order a rule to take
    precedence, which is the schema's "order is precedence".
    """
    tree = BlockTree.build(
        block(
            BlockKind.DOCUMENT,
            children=(
                block(BlockKind.HEADING, text="Schedule 1", level=1),
                block(BlockKind.HEADING, text="Schedule 2", level=2),
            ),
        )
    )

    ancestor_first = apply_semantics(
        tree, profile_from_mapping({"name": "closest", "role_rules": ORDERED})
    )
    heading_first = apply_semantics(
        tree,
        profile_from_mapping({"name": "closest", "role_rules": ORDERED[::-1]}),
    )

    assert texted(ancestor_first, "Schedule 2").role == "body"
    assert texted(ancestor_first, "Schedule 2").attrs["semantic"]["role_rule"] == 0
    assert texted(heading_first, "Schedule 2").role == "schedule"


# --- spans: overlap, order and what was already there ----------------------


OVERLAPPING = profile_from_mapping(
    {
        "name": "overlapping",
        "span_extractors": [
            {"type": "party", "pattern": r"the (Supplier|Customer)", "group": 1},
            {"type": "defined_term", "pattern": r"\b(Supplier)\b", "group": 1},
            {"type": "party", "pattern": r"\b(Supplier)\b", "group": 1},
        ],
    }
)


def test_two_extractors_may_cover_the_same_text_with_different_types() -> None:
    """A range can honestly be both; only a repeat of one type is dropped."""
    spans = extract_spans("the Supplier shall pay", profile=OVERLAPPING)

    assert [(span.type, span.start, span.end) for span in spans] == [
        ("party", 4, 12),
        ("defined_term", 4, 12),
    ]


def test_spans_come_out_in_extractor_order() -> None:
    profile = profile_from_mapping(
        {
            "name": "ordered",
            "span_extractors": [
                {"type": "amount", "pattern": r"(£\d+)", "group": 1},
                {"type": "date", "pattern": r"(2026-01-31)", "group": 1},
            ],
        }
    )

    spans = extract_spans("Due 2026-01-31: £50", profile=profile)

    assert [span.type for span in spans] == ["amount", "date"]


def test_spans_already_on_a_block_are_kept(contract: Profile) -> None:
    """A span a reader took from the format itself (ADR-0024) is not thrown away."""
    tree = BlockTree.build(
        block(
            BlockKind.DOCUMENT,
            children=(
                block(
                    BlockKind.PARAGRAPH,
                    text="The Supplier shall pay USD 500.",
                    spans=(Span(type="emphasis", start=4, end=12),),
                ),
            ),
        )
    )

    applied = apply_semantics(tree, contract)
    paragraph = applied.block_at("/paragraph[1]")

    assert [span.type for span in paragraph.spans] == ["emphasis", "party", "amount"]


def test_an_extractor_group_its_pattern_does_not_have_is_an_error() -> None:
    """`load_profile` rejects this; a hand-built `Profile` can still carry it."""
    from redlines.profiles import SpanExtractor

    profile = Profile(
        name="broken",
        span_extractors=(SpanExtractor(type="date", pattern=r"\d+", group=2),),
    )

    with pytest.raises(ValueError, match="group 2"):
        extract_spans("2026", profile=profile)


# --- the pass's own promises -----------------------------------------------


def test_a_profile_with_no_rules_leaves_the_tree_alone(contract: Profile) -> None:
    """Nothing declared, nothing claimed -- the ADR-0006 degrade path (D30)."""
    tree = PlainTextReader().read(CONTRACT, profile=contract)
    empty = profile_from_mapping({"name": "nothing"})

    assert apply_semantics(tree, empty).to_dict() == tree.to_dict()


def test_the_pass_never_touches_the_tree_it_was_given(contract: Profile) -> None:
    tree = PlainTextReader().read(CONTRACT, profile=contract)
    before = tree.to_dict()

    apply_semantics(tree, contract)

    assert tree.to_dict() == before


def test_the_pass_is_deterministic(contract: Profile) -> None:
    """N1: the same tree and profile give an identical result, twice over."""
    first = read(CONTRACT, contract)
    second = read(CONTRACT, contract)

    assert first.to_dict() == second.to_dict()


def test_applying_the_pass_twice_is_applying_it_once(contract: Profile) -> None:
    once = read(CONTRACT, contract)

    assert apply_semantics(once, contract).to_dict() == once.to_dict()


@pytest.mark.parametrize(
    "fixture", sorted(path.stem for path in HARD_CASES.glob("*.txt"))
)
@pytest.mark.parametrize("profile_name", ["generic", "contract", "markdown"])
def test_every_builtin_profile_survives_every_hard_case(
    profile_name: str, fixture: str
) -> None:
    """The § 6b hard cases, read and then given semantics: no crash, no drift.

    `tests/test_reader_profiles_integration.py` does this for the reader; the
    pass runs over the same trees, including the PDF-extracted fixture whose
    structure is allowed to be wrong (R8a) as long as nothing falls over.
    """
    source = (HARD_CASES / f"{fixture}.txt").read_text(encoding="utf-8")
    profile = builtin_profile(profile_name)

    tree = read(source, profile)

    assert tree.root.kind is BlockKind.DOCUMENT
    assert read(source, profile).to_dict() == tree.to_dict()
    assert apply_semantics(tree, profile).to_dict() == tree.to_dict()
    for found in tree.walk():
        assert all(span.end <= len(found.text) for span in found.spans)


def test_the_pass_keeps_the_shape_the_reader_gave_it(contract: Profile) -> None:
    """Addresses, kinds, labels, ``dropped`` and ``matched_by`` are the reader's."""
    tree = PlainTextReader().read(CONTRACT, profile=contract)

    applied = apply_semantics(tree, contract)

    assert [(found.path, found.kind, found.label) for found in applied.walk()] == [
        (found.path, found.kind, found.label) for found in tree.walk()
    ]
    assert [found.matched_by for found in applied.walk()] == [
        found.matched_by for found in tree.walk()
    ]
    assert applied.dropped == tree.dropped
    assert applied.fallback_count == tree.fallback_count


# --- the twin promise (PRD § 6b) -------------------------------------------
#
# "A markdown contract with `## 7. Termination` and `1.` list items therefore
# gets the same roles and labels as its plain-text twin." Now that the
# markdown reader (#103) is merged, the promise is tested on what the two
# readers actually build from the twin pair in tests/corpus/markdown_cases/ --
# the same agreement written once in markdown and once in plain text -- rather
# than on trees written out by hand here.
#
# The same promise over the milestone's own forty-clause document, spans and
# cross-reference values included, is tests/test_sample_pair.py (#108).

MARKDOWN_CASES = Path(__file__).parent / "corpus" / "markdown_cases"


def twin_trees() -> tuple[BlockTree, BlockTree]:
    """The twin pair after the semantic pass: the plain text read by
    `PlainTextReader` under ``contract``, the markdown read by `MarkdownReader`
    under ``markdown``."""
    contract, markdown = builtin_profile("contract"), builtin_profile("markdown")
    plain = apply_semantics(
        PlainTextReader().read(
            (MARKDOWN_CASES / "twin_contract.txt").read_text(encoding="utf-8"),
            profile=contract,
        ),
        contract,
    )
    marked = apply_semantics(
        MarkdownReader().read(
            (MARKDOWN_CASES / "twin_contract.md").read_text(encoding="utf-8"),
            profile=markdown,
        ),
        markdown,
    )
    return plain, marked


def test_a_markdown_contract_gets_the_same_roles_as_its_plain_text_twin() -> None:
    plain, marked = twin_trees()

    assert roles(plain) == roles(marked)
    assert roles(plain) == [
        ("Master Services Agreement", None),
        (
            "This Agreement is made between Acme Analytics Ltd and Beta Retail plc.",
            None,
        ),
        ("3", None),
        ("3.1", None),
        ("The Supplier issues invoices monthly in arrears.", None),
        ("(a)", None),
        ("(b)", None),
        ("7", None),
        ("7.1", None),
        ("7.2", None),
        ("Schedule 1", "schedule"),
        ("1", "schedule"),
        ("2", "schedule"),
    ]


def test_the_twins_carry_the_same_spans_block_by_block() -> None:
    """Spans are compared by type and value, never by offset: the markdown
    syntax the reader strips would shift every offset in the block."""
    plain, marked = twin_trees()

    assert [
        [(span.type, span.value) for span in block.spans] for block in plain.walk()
    ] == [[(span.type, span.value) for span in block.spans] for block in marked.walk()]
    # And there is something to compare: the party spans the contract and
    # markdown profiles both extract.
    assert [
        (span.type, span.value) for block in plain.walk() for span in block.spans
    ] == [("party", None), ("party", None)]
