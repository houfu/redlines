"""Tests for `redlines.pipeline.read_document`, the M1 read pipeline in one call.

The function itself decides almost nothing: it settles a format, settles a
profile, calls a reader and runs the semantic pass. So these tests are about
those four hand-offs — that detection is consulted only when no format is
given and its reason survives to the caller, that all four shapes of the
``profile`` argument arrive as the same profile, that the recorded defaults
(PRD § 6b, ROADMAP § 5.2) are what a caller gets for nothing, that the size cap
still bites, and that the tree coming out is the reader's tree *after*
semantics rather than before.

`tests/test_sample_pair.py` is the other half of this: it builds the same trees
without going through `read_document` and compares them with the goldens the
regenerate script writes through it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from redlines.blocks import Block, BlockKind, BlockTree
from redlines.pipeline import DEFAULT_PROFILES, read_document
from redlines.profiles import Profile, builtin_profile, profile_from_mapping
from redlines.readers import (
    DEFAULT_MAX_CHARS,
    Reader,
    reader_for,
    register_reader,
    unregister_reader,
)

CONTRACT_TEXT = """\
MASTER SERVICES AGREEMENT

1. DEFINITIONS

1.1 "Confidential Information" means information disclosed by one party to
the other and marked as confidential.

7. TERMINATION

7.1 Either party may terminate this agreement on thirty days' notice.

7.2 The Customer shall pay all Charges due under clause 7.1 on termination.
"""

CONTRACT_MARKDOWN = """\
# Master Services Agreement

## 1. Definitions

1. "Confidential Information" means information disclosed by one party to the
   other and marked as confidential.

## 7. Termination

1. Either party may terminate this agreement on thirty days' notice.
"""


def roles(tree: BlockTree) -> list[str]:
    """Return every role assigned in ``tree``, in document order."""
    return [block.role for block in tree.walk() if block.role is not None]


def span_types(tree: BlockTree) -> list[str]:
    """Return every span type in ``tree``, in document order."""
    return [span.type for block in tree.walk() for span in block.spans]


class _CaplessReader:
    """A conforming reader that takes only what the `Reader` protocol promises.

    The protocol's ``read`` is ``(source, *, profile)``; ``max_chars`` is an
    extra every reader in this package happens to accept. This one does not, so
    it exercises the branch where `read_document` applies the cap itself.
    """

    name = "capless"
    formats = ("capless",)

    def read(self, source: str | bytes, *, profile: Profile | None = None) -> BlockTree:
        """Return the whole source as one paragraph, ignoring everything else."""
        text = source.decode("utf-8") if isinstance(source, bytes) else source
        return BlockTree.build(
            Block(
                kind=BlockKind.DOCUMENT,
                children=(Block(kind=BlockKind.PARAGRAPH, text=text),),
            )
        )


# The format hand-off


def test_explicit_format_is_used_as_given() -> None:
    """A named format is never second-guessed by detection."""
    tree = read_document(CONTRACT_TEXT, format="text")

    assert tree.root.attrs["reader"] == reader_for("text").name
    assert [block.label for block in tree.walk() if block.label] == [
        "1",
        "1.1",
        "7",
        "7.1",
        "7.2",
    ]


def test_explicit_format_wins_over_a_contradicting_path() -> None:
    """``path`` is detection's input, so an explicit format overrides it."""
    tree = read_document(CONTRACT_MARKDOWN, format="text", path="agreement.md")

    assert tree.root.attrs["reader"] == reader_for("text").name


def test_format_detected_from_the_path() -> None:
    """A ``.md`` name settles the format without looking at the content."""
    tree = read_document(CONTRACT_MARKDOWN, path="agreement.md")

    assert tree.root.attrs["reader"] == reader_for("markdown").name
    assert any(block.kind is BlockKind.HEADING for block in tree.walk())


def test_format_detected_from_the_path_as_a_path_object() -> None:
    """``path`` takes anything os.fspath understands, not only a string."""
    tree = read_document(CONTRACT_TEXT, path=Path("contracts") / "agreement.txt")

    assert tree.root.attrs["reader"] == reader_for("text").name


def test_format_detected_from_the_content() -> None:
    """With no path at all, the content decides — here, an ATX heading."""
    tree = read_document(CONTRACT_MARKDOWN)

    assert tree.root.attrs["reader"] == reader_for("markdown").name


def test_content_with_no_markdown_syntax_detects_as_text() -> None:
    """The other side of the same hand-off: plain prose is text."""
    tree = read_document(CONTRACT_TEXT)

    assert tree.root.attrs["reader"] == reader_for("text").name


def test_undetectable_format_raises_quoting_the_reason() -> None:
    """A ``.docx`` is a real answer from detection, and the caller gets it.

    The "coming in 1.1" sentence is written for a person to read and is the
    only promise redlines makes about the formats it does not read yet, so it
    has to survive the pipeline rather than be flattened into "unsupported".
    """
    with pytest.raises(ValueError) as error:
        read_document(b"PK\x03\x04binary", path="agreement.docx")

    message = str(error.value)
    assert "'.docx' extension is a DOCX file" in message
    assert "coming in 1.1" in message
    assert "format=" in message


def test_unreadable_content_raises_quoting_the_reason() -> None:
    """Undetectable content with no path is reported the same way."""
    with pytest.raises(ValueError) as error:
        read_document(b"\x89PNG\r\n\x1a\n\x00\x01")

    assert "binary" in str(error.value)


# The profile hand-off


def test_profile_by_builtin_name() -> None:
    """A built-in name resolves through `builtin_profile`."""
    tree = read_document(CONTRACT_TEXT, format="text", profile="contract")

    assert "definitions" in roles(tree)


def test_profile_as_a_profile_object() -> None:
    """A `Profile` is used as it is, with no re-validation."""
    profile = builtin_profile("contract")
    tree = read_document(CONTRACT_TEXT, format="text", profile=profile)

    assert roles(tree) == roles(read_document(CONTRACT_TEXT, format="text"))


# A profile small enough to read in one glance, in the two shapes a caller
# can hand one over in without a file: enough label and heading rules for the
# reader to find "7. TERMINATION" as a heading, and one role rule on it.
INLINE_PROFILE: dict[str, Any] = {
    "name": "inline",
    "label_patterns": [
        {
            "name": "decimal",
            "pattern": r"^(\d+(?:\.\d+)*)\.?\s+",
            "style": "decimal",
            "depth_mode": "arithmetic",
        }
    ],
    "heading_rule": {
        "max_words": 4,
        "allow_all_caps": True,
        "forbid_terminal_punctuation": True,
    },
    "role_rules": [
        {"role": "termination", "match": "heading", "pattern": "(?i)^TERMIN"}
    ],
}

INLINE_PROFILE_YAML = """\
name: inline
label_patterns:
  - name: decimal
    pattern: '^(\\d+(?:\\.\\d+)*)\\.?\\s+'
    style: decimal
    depth_mode: arithmetic
heading_rule:
  max_words: 4
  allow_all_caps: true
  forbid_terminal_punctuation: true
role_rules:
  - role: termination
    match: heading
    pattern: '(?i)^TERMIN'
"""


def test_profile_as_a_mapping() -> None:
    """A mapping goes through `profile_from_mapping`."""
    tree = read_document(CONTRACT_TEXT, format="text", profile=INLINE_PROFILE)

    assert roles(tree) == ["termination"]


def test_profile_from_a_yaml_file(tmp_path: Path) -> None:
    """A path goes through `load_profile`, which reads the file.

    The same profile as `INLINE_PROFILE`, written out as YAML: a file and a
    mapping saying the same thing must give the same tree.
    """
    profile_file = tmp_path / "house.yaml"
    profile_file.write_text(INLINE_PROFILE_YAML, encoding="utf-8")

    from_file = read_document(CONTRACT_TEXT, format="text", profile=str(profile_file))
    from_path = read_document(CONTRACT_TEXT, format="text", profile=profile_file)

    assert roles(from_file) == ["termination"]
    assert from_path.to_dict() == from_file.to_dict()
    assert (
        from_file.to_dict()
        == read_document(CONTRACT_TEXT, format="text", profile=INLINE_PROFILE).to_dict()
    )


def test_a_builtin_name_beats_a_file_of_the_same_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``profile="contract"`` is the built-in even next to a file called that.

    `load_profile` treats a string naming an existing file as that file, so the
    built-in names are checked first; otherwise a stray ``contract`` in the
    working directory would silently take over.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "contract").write_text("name: impostor\n", encoding="utf-8")

    tree = read_document(CONTRACT_TEXT, format="text", profile="contract")

    assert "definitions" in roles(tree)


def test_profile_object_and_name_give_the_same_tree() -> None:
    """The four shapes are four spellings of one argument, not four paths."""
    by_name = read_document(CONTRACT_TEXT, format="text", profile="contract")
    by_object = read_document(
        CONTRACT_TEXT, format="text", profile=builtin_profile("contract")
    )

    assert by_object.to_dict() == by_name.to_dict()


# The recorded defaults (PRD § 6b, ROADMAP § 5.2)


def test_default_profile_for_text_is_contract() -> None:
    """1.0 defaults plain text to ``contract`` (ROADMAP § 5.2)."""
    assert DEFAULT_PROFILES["text"] == "contract"

    defaulted = read_document(CONTRACT_TEXT, format="text")
    named = read_document(CONTRACT_TEXT, format="text", profile="contract")

    assert defaulted.to_dict() == named.to_dict()


def test_default_profile_for_markdown_is_markdown() -> None:
    """And ``.md`` to ``markdown``, which is what detection returns for it."""
    assert DEFAULT_PROFILES["markdown"] == "markdown"

    defaulted = read_document(CONTRACT_MARKDOWN, path="agreement.md")
    named = read_document(CONTRACT_MARKDOWN, path="agreement.md", profile="markdown")

    assert defaulted.to_dict() == named.to_dict()


def test_a_format_with_no_recorded_default_says_so() -> None:
    """A third party's format has no default, and none is invented for it."""
    reader = _CaplessReader()
    register_reader(reader)
    try:
        with pytest.raises(ValueError) as error:
            read_document("anything", format=reader.formats[0])
    finally:
        unregister_reader(reader.formats[0])

    message = str(error.value)
    assert "no default profile is recorded" in message
    assert "profile=" in message


def test_an_unknown_format_reaches_the_registry() -> None:
    """A named format nobody reads is the registry's error to report."""
    with pytest.raises(LookupError) as error:
        read_document(CONTRACT_TEXT, format="klingon", profile="generic")

    assert "klingon" in str(error.value)


# The size cap (ADR-0028)


def test_max_chars_reaches_the_reader() -> None:
    """A cap below the document's length is refused, by the reader itself."""
    with pytest.raises(ValueError) as error:
        read_document(CONTRACT_TEXT, format="text", max_chars=20)

    assert "over the 20 character limit" in str(error.value)


def test_max_chars_defaults_to_the_shared_cap() -> None:
    """And the default is the readers' own default, not a second opinion."""
    assert (
        read_document(CONTRACT_TEXT, format="text").to_dict()
        == read_document(
            CONTRACT_TEXT, format="text", max_chars=DEFAULT_MAX_CHARS
        ).to_dict()
    )


def test_max_chars_is_enforced_for_a_reader_that_does_not_take_it() -> None:
    """The cap means the same thing whichever reader answers."""
    reader = _CaplessReader()
    assert isinstance(reader, Reader)
    register_reader(reader)
    try:
        with pytest.raises(ValueError) as error:
            read_document(
                CONTRACT_TEXT,
                format=reader.formats[0],
                profile="generic",
                max_chars=20,
            )
        assert (
            read_document("one paragraph", format=reader.formats[0], profile="generic")
            .root.children[0]
            .text
            == "one paragraph"
        )
    finally:
        unregister_reader(reader.formats[0])

    assert "over the 20 character limit" in str(error.value)


# What comes out


def test_the_result_carries_what_the_bare_reader_does_not() -> None:
    """The tree is the reader's tree *after* the semantic pass, always.

    The comparison is the point: same source, same profile, same reader — the
    only difference is that `read_document` ran `apply_semantics` and the
    direct reader call did not.
    """
    profile = builtin_profile("contract")
    structure_only = reader_for("text").read(CONTRACT_TEXT, profile=profile)
    interpreted = read_document(CONTRACT_TEXT, format="text", profile=profile)

    assert roles(structure_only) == []
    assert span_types(structure_only) == []
    assert "definitions" in roles(interpreted)
    assert "definition" in roles(interpreted)
    assert "defined_term" in span_types(interpreted)
    assert "cross_reference" in span_types(interpreted)

    # Structure is untouched: only roles and spans were added.
    assert [(block.kind, block.label, block.path) for block in interpreted.walk()] == [
        (block.kind, block.label, block.path) for block in structure_only.walk()
    ]


def test_a_cross_reference_span_carries_the_referenced_label() -> None:
    """The fact M2 needs from this pipeline: clause 7.1 is named, not quoted."""
    tree = read_document(CONTRACT_TEXT, format="text")

    values = [
        span.value
        for block in tree.walk()
        for span in block.spans
        if span.type == "cross_reference"
    ]
    assert "7.1" in values


def test_a_profile_with_no_rules_leaves_the_tree_bare() -> None:
    """``generic`` runs the same pipeline and assigns nothing (ADR-0006)."""
    tree = read_document(CONTRACT_TEXT, format="text", profile="generic")

    assert roles(tree) == []
    assert span_types(tree) == []


def test_two_calls_give_the_same_tree(tmp_path: Path) -> None:
    """Determinism (N1), end to end and through every hand-off."""
    first = read_document(CONTRACT_MARKDOWN, path="agreement.md")
    second = read_document(CONTRACT_MARKDOWN, path="agreement.md")

    assert first.to_dict() == second.to_dict()

    inline = profile_from_mapping(INLINE_PROFILE)
    assert (
        read_document(CONTRACT_TEXT, format="text", profile=inline).to_dict()
        == read_document(CONTRACT_TEXT, format="text", profile=inline).to_dict()
    )
