"""Tests for the reader protocol, the registry and the paragraph reader (#105)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from redlines.blocks import (
    MATCHED_BY_DOCUMENT,
    MATCHED_BY_FALLBACK,
    Block,
    BlockKind,
    BlockTree,
)
from redlines.profiles import Profile
from redlines.readers import (
    DEFAULT_MAX_CHARS,
    ParagraphReader,
    Reader,
    check_size,
    decode_source,
    reader_for,
    readers,
    register_reader,
    unregister_reader,
)

CONTRACT = """\
Master Services Agreement

1. Interpretation

In this agreement, "Services" means the services described in Schedule 1.

2. Term

This agreement starts on the Commencement Date.
"""


class ClauseReader:
    """A reader a third party could have written, for a format of its own.

    Nothing here imports a base class: three members are the whole contract.
    """

    name = "clause"
    formats = ("clause",)

    def read(self, source: str | bytes, *, profile: Profile | None = None) -> BlockTree:
        text = source.decode("utf-8") if isinstance(source, bytes) else source
        return BlockTree.build(
            Block(
                kind=BlockKind.DOCUMENT,
                matched_by=MATCHED_BY_DOCUMENT,
                confidence=1.0,
                children=tuple(
                    Block(
                        kind=BlockKind.LIST_ITEM,
                        text=line.strip(),
                        matched_by="clause:line",
                        confidence=1.0,
                    )
                    for line in text.splitlines()
                    if line.strip()
                ),
            )
        )


class NotAReader:
    """Has a name, but no formats and no ``read``."""

    name = "impostor"


@pytest.fixture
def clean_registry() -> Iterator[None]:
    """Restore the registry after a test adds to or replaces part of it."""
    before = dict(readers())
    yield
    for fmt in set(readers()) - set(before):
        unregister_reader(fmt)
    for fmt, reader in before.items():
        register_reader(reader, replace=True)


# --- the protocol ----------------------------------------------------------


def test_the_builtin_reader_is_a_reader() -> None:
    assert isinstance(ParagraphReader(), Reader)


def test_a_third_party_class_is_a_reader_without_inheriting_anything() -> None:
    assert ClauseReader.__mro__ == (ClauseReader, object)
    assert isinstance(ClauseReader(), Reader)


def test_an_object_missing_the_members_is_not_a_reader() -> None:
    assert not isinstance(NotAReader(), Reader)
    assert not isinstance(object(), Reader)


def test_a_reader_declares_a_name_and_the_formats_it_claims() -> None:
    reader = ParagraphReader()
    assert reader.name == "paragraph"
    assert reader.formats == ("text",)


# --- the registry ----------------------------------------------------------


def test_the_paragraph_reader_is_registered_for_text() -> None:
    assert isinstance(reader_for("text"), ParagraphReader)


def test_readers_maps_format_names_to_readers() -> None:
    assert readers()["text"].name == "paragraph"


def test_readers_is_sorted_and_a_copy() -> None:
    listing = readers()
    assert list(listing) == sorted(listing)
    listing["invented"] = ParagraphReader()
    assert "invented" not in readers()


def test_a_third_party_reader_can_claim_a_new_format(clean_registry: None) -> None:
    register_reader(ClauseReader())

    assert set(readers()) == {"text", "clause"}
    found = reader_for("clause")
    assert found.name == "clause"
    assert found.read("1.1 A clause.\n1.2 Another.").fallback_count == 0


def test_registering_over_a_claimed_format_is_refused(clean_registry: None) -> None:
    class Rival:
        name = "rival"
        formats = ("text",)

        def read(
            self, source: str | bytes, *, profile: Profile | None = None
        ) -> BlockTree:
            return BlockTree.build(Block(kind=BlockKind.DOCUMENT))

    with pytest.raises(ValueError, match="already read by 'paragraph'"):
        register_reader(Rival())
    assert reader_for("text").name == "paragraph"


def test_replace_takes_a_format_over(clean_registry: None) -> None:
    class Replacement:
        name = "plaintext"
        formats = ("text",)

        def read(
            self, source: str | bytes, *, profile: Profile | None = None
        ) -> BlockTree:
            return BlockTree.build(Block(kind=BlockKind.DOCUMENT))

    register_reader(Replacement(), replace=True)
    assert reader_for("text").name == "plaintext"


def test_a_reader_claiming_no_formats_is_refused(clean_registry: None) -> None:
    class Unclaimed:
        name = "unclaimed"
        formats: tuple[str, ...] = ()

        def read(
            self, source: str | bytes, *, profile: Profile | None = None
        ) -> BlockTree:
            return BlockTree.build(Block(kind=BlockKind.DOCUMENT))

    with pytest.raises(ValueError, match="claims no formats"):
        register_reader(Unclaimed())


def test_registering_something_that_is_not_a_reader_is_refused() -> None:
    with pytest.raises(TypeError, match="is not a Reader"):
        register_reader(NotAReader())  # type: ignore[arg-type]


def test_an_unknown_format_names_the_formats_that_are_known() -> None:
    with pytest.raises(LookupError) as error:
        reader_for("docx")
    assert "docx" in str(error.value)
    assert "text" in str(error.value)


def test_unregistering_a_format_nobody_claims_is_not_an_error() -> None:
    unregister_reader("nothing-claims-this")


def test_a_reader_claiming_two_formats_gets_both(clean_registry: None) -> None:
    class TwoFormats:
        name = "two"
        formats = ("alpha", "beta")

        def read(
            self, source: str | bytes, *, profile: Profile | None = None
        ) -> BlockTree:
            return BlockTree.build(Block(kind=BlockKind.DOCUMENT))

    register_reader(TwoFormats())
    assert reader_for("alpha") is reader_for("beta")


def test_a_refused_registration_claims_none_of_its_formats(
    clean_registry: None,
) -> None:
    class Greedy:
        name = "greedy"
        formats = ("greedy-format", "text")

        def read(
            self, source: str | bytes, *, profile: Profile | None = None
        ) -> BlockTree:
            return BlockTree.build(Block(kind=BlockKind.DOCUMENT))

    with pytest.raises(ValueError, match="already read by"):
        register_reader(Greedy())
    assert "greedy-format" not in readers()


# --- the paragraph reader --------------------------------------------------


def test_one_block_per_blank_line_separated_paragraph() -> None:
    tree = ParagraphReader().read(CONTRACT)

    assert tree.root.kind is BlockKind.DOCUMENT
    assert [block.text for block in tree.root.children] == [
        "Master Services Agreement",
        "1. Interpretation",
        'In this agreement, "Services" means the services described in Schedule 1.',
        "2. Term",
        "This agreement starts on the Commencement Date.",
    ]
    assert all(block.kind is BlockKind.PARAGRAPH for block in tree.root.children)


def test_every_block_says_nothing_recognised_it() -> None:
    tree = ParagraphReader().read(CONTRACT)

    for block in tree.root.children:
        assert block.matched_by == MATCHED_BY_FALLBACK
        assert block.confidence == 0.0
        assert block.role is None
        assert block.label is None
        assert block.spans == ()


def test_the_fallback_count_is_every_block_but_the_root() -> None:
    tree = ParagraphReader().read(CONTRACT)
    assert tree.fallback_count == 5
    assert tree.root.matched_by == MATCHED_BY_DOCUMENT


def test_the_paragraph_reader_drops_nothing() -> None:
    assert ParagraphReader().read(CONTRACT).dropped == ()


def test_paragraphs_are_addressed() -> None:
    tree = ParagraphReader().read(CONTRACT)
    assert [block.path for block in tree.walk()][:3] == [
        "/",
        "/paragraph[1]",
        "/paragraph[2]",
    ]


def test_the_root_records_which_reader_made_the_tree() -> None:
    assert ParagraphReader().read(CONTRACT).root.attrs == {"reader": "paragraph"}


@pytest.mark.parametrize(
    "text",
    [
        "One.\n\nTwo.",
        "One.\r\n\r\nTwo.",
        "One.\n   \nTwo.",
        "\n\nOne.\n\n\n\nTwo.\n\n",
    ],
)
def test_paragraph_breaks_survive_line_ending_and_whitespace_noise(text: str) -> None:
    assert [block.text for block in ParagraphReader().read(text).root.children] == [
        "One.",
        "Two.",
    ]


def test_a_hard_wrapped_paragraph_stays_one_block() -> None:
    tree = ParagraphReader().read("A line\nand its continuation.\n\nAnother.")
    assert tree.root.children[0].text == "A line\nand its continuation."


def test_an_empty_document_is_a_root_and_nothing_else() -> None:
    tree = ParagraphReader().read("   \n\n  \n")
    assert tree.root.children == ()
    assert tree.fallback_count == 0


def test_bytes_are_decoded_as_utf_8() -> None:
    tree = ParagraphReader().read("Fee: €1,000.\n\nPaid.".encode("utf-8"))
    assert tree.root.children[0].text == "Fee: €1,000."


def test_bytes_that_are_not_utf_8_are_refused() -> None:
    with pytest.raises(ValueError, match="not UTF-8"):
        ParagraphReader().read(b"\xff\xfe\x00A")


def test_a_profile_is_accepted_and_ignored() -> None:
    profile = Profile(name="contract")
    assert ParagraphReader().read(CONTRACT, profile=profile) == ParagraphReader().read(
        CONTRACT
    )


def test_reading_the_same_source_twice_gives_the_same_tree() -> None:
    assert ParagraphReader().read(CONTRACT) == ParagraphReader().read(CONTRACT)
    first = ParagraphReader().read(CONTRACT).to_dict()
    assert first == ParagraphReader().read(CONTRACT).to_dict()


# --- the input size cap (ADR-0028) -----------------------------------------


def test_the_default_cap_is_two_million_characters() -> None:
    assert DEFAULT_MAX_CHARS == 2_000_000


def test_a_source_over_the_cap_is_refused() -> None:
    with pytest.raises(ValueError, match="over the 10 character limit"):
        ParagraphReader().read("x" * 11, max_chars=10)


def test_a_source_at_the_cap_is_read() -> None:
    assert ParagraphReader().read("x" * 10, max_chars=10).fallback_count == 1


def test_check_size_names_the_reader_that_refused() -> None:
    with pytest.raises(ValueError, match="^markdown:"):
        check_size("x" * 3, max_chars=2, reader="markdown")


def test_decode_source_passes_text_through() -> None:
    assert decode_source("already text", reader="paragraph") == "already text"


def test_decode_source_refuses_something_that_is_neither() -> None:
    with pytest.raises(TypeError, match="expected str or bytes"):
        decode_source(42, reader="paragraph")  # type: ignore[arg-type]
