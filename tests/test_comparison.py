"""Tests for `redlines.comparison` -- the public entry point (#136, ADR-0033).

What is asserted here is the API rather than the engine: what `compare`
accepts, what it refuses, what a `redlines.comparison.Comparison` records
about how it was produced, and what its JSON looks like. The engine's own
answers are pinned in ``tests/test_alignment.py``, ``tests/test_changes.py``
and ``tests/test_sample_pair_change_tree.py``.

Four groups.

The first is the argument surface: a bare ``str`` is content and never a path;
a `redlines.document.Document` is how a file gets in; a
`redlines.blocks.BlockTree` skips reading; format detection happens per side
and says so when the two sides disagree.

The second is the record: `redlines.comparison.ComparisonConfig` carries the
two formats, the profile, the alignment configuration whole, the *resolved*
similarity backend and the leaf differ's name, so a payload can be read back
without guessing what produced it.

The third is the wire shape -- the top-level keys of ADR-0033's v2 document,
the optional alignment, the version checking on the way back in.

The fourth is determinism (#135): the same two documents compared in two
processes under different string-hash seeds produce byte-identical JSON.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.helpers.hash_seed import assert_byte_identical_across_hash_seeds
from redlines import compare
from redlines.alignment import AlignmentConfig
from redlines.blocks import Block, BlockKind, BlockTree
from redlines.comparison import (
    BLOCKS_FORMAT,
    SCHEMA_VERSION,
    Comparison,
    ComparisonConfig,
)
from redlines.document import Document
from redlines.pipeline import read_document
from redlines.processor import (
    Chunk,
    DiffOperation,
    RedlinesProcessor,
    tokenize_text,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CASE_DIR = Path(__file__).parent / "corpus" / "sample_pair"

SOURCE_MARKDOWN = "# Agreement\n\n1. The Supplier responds within four hours.\n"
TEST_MARKDOWN = "# Agreement\n\n1. The Supplier responds within two hours.\n"
SOURCE_TEXT = "AGREEMENT\n\n1. The Supplier responds within four hours.\n"
TEST_TEXT = "AGREEMENT\n\n1. The Supplier responds within two hours.\n"


class InMemoryDocument(Document):
    """The smallest possible `redlines.document.Document`, held in memory.

    `redlines.document.PlainTextFile` would need a file on disk; what is being
    tested is that `compare` accepts the *interface*, which is the ADR-0003
    facade type a file arrives through.
    """

    def __init__(self, text: str) -> None:
        self._text = text

    @property
    def text(self) -> str:
        """The document's text."""
        return self._text


class WholeBlockProcessor(RedlinesProcessor):
    """A custom leaf differ that reports any difference as one whole-block replace.

    Deliberately not a subclass of
    `redlines.processor.WholeDocumentProcessor`: R17 says the leaf differ is
    pluggable, and a third party's will not inherit from ours.
    """

    def process(
        self, source: Document | str, test: Document | str
    ) -> list[DiffOperation]:
        """Report the whole of one text becoming the whole of the other."""
        source_text = source.text if isinstance(source, Document) else source
        test_text = test.text if isinstance(test, Document) else test
        source_tokens = tokenize_text(source_text)
        test_tokens = tokenize_text(test_text)
        if source_text == test_text:
            return []
        return [
            DiffOperation(
                source_chunk=Chunk(text=source_tokens, chunk_location=None),
                test_chunk=Chunk(text=test_tokens, chunk_location=None),
                opcodes=("replace", 0, len(source_tokens), 0, len(test_tokens)),
            )
        ]


# --- what `compare` accepts ------------------------------------------------


def test_a_bare_string_is_content_and_never_a_path(tmp_path: Path) -> None:
    """ADR-0033's rule: the library does not stat the filesystem behind you.

    A one-line contract that happens to name a file on the server's disk must
    be compared as itself. The file here says something completely different,
    so if `compare` ever read it the assertion below would fail.
    """
    decoy = tmp_path / "source.md"
    decoy.write_text("# Something else entirely\n", encoding="utf-8")
    result = compare(str(decoy), str(decoy), format="text")
    assert result.source.root.children[0].text.endswith("source.md")
    assert list(result.changes) == []


def test_a_document_is_how_a_file_gets_in() -> None:
    """The ADR-0003 facade type stays load-bearing rather than being replaced."""
    result = compare(
        InMemoryDocument(SOURCE_TEXT),
        InMemoryDocument(TEST_TEXT),
        format="text",
    )
    assert [str(change.kind) for change in result.changes] == ["modify"]
    assert result.config.source_format == "text"


def test_a_block_tree_skips_reading_entirely() -> None:
    """How the M3 facade, the benchmark harness and the site hand in their own trees.

    Nothing was read, so there is no format and no profile to record, and
    `compare` says exactly that rather than guessing one.
    """
    source = read_document(SOURCE_TEXT, format="text", profile="contract")
    test = read_document(TEST_TEXT, format="text", profile="contract")
    result = compare(source, test)
    assert result.source is source
    assert result.test is test
    assert (result.config.source_format, result.config.test_format) == (
        BLOCKS_FORMAT,
        BLOCKS_FORMAT,
    )
    assert result.config.profile == ""
    assert [str(change.kind) for change in result.changes] == ["modify"]


def test_one_side_may_be_a_tree_and_the_other_a_document() -> None:
    """A legitimate mixture: only one side needed reading, so only it has a format."""
    source = read_document(SOURCE_TEXT, format="text", profile="contract")
    result = compare(source, TEST_TEXT, format="text")
    assert (result.config.source_format, result.config.test_format) == (
        BLOCKS_FORMAT,
        "text",
    )
    assert result.config.profile == "contract"


# --- format detection, per side --------------------------------------------


def test_each_side_is_detected_on_its_own() -> None:
    """Detection reads each document's own hint and content, not the pair's."""
    result = compare(
        SOURCE_MARKDOWN,
        TEST_MARKDOWN,
        source_path="source.md",
        test_path="test.md",
    )
    assert (result.config.source_format, result.config.test_format) == (
        "markdown",
        "markdown",
    )
    assert result.config.profile == "markdown"


def test_two_sides_that_detect_differently_are_refused() -> None:
    """Comparing a markdown document against a plain-text one is almost always a mistake.

    Reading them under one format silently would hide it; the error names both
    formats and says how to override.
    """
    with pytest.raises(ValueError, match="detected the source document as"):
        compare(
            SOURCE_MARKDOWN,
            TEST_TEXT,
            source_path="source.md",
            test_path="test.txt",
        )


def test_an_explicit_format_settles_both_sides() -> None:
    """``format=`` is the override the mismatch error points at."""
    result = compare(
        SOURCE_MARKDOWN, TEST_TEXT, format="text", source_path="source.md"
    )
    assert (result.config.source_format, result.config.test_format) == ("text", "text")


def test_an_undetectable_side_is_named_in_the_error() -> None:
    """The detection's own reason is quoted, and the failing side is said out loud."""
    with pytest.raises(ValueError, match="the source document is"):
        compare("", "", source_path="agreement.docx", test_path="agreement.docx")


# --- what the comparison records -------------------------------------------


def test_the_configuration_records_what_actually_ran() -> None:
    """One source of truth for the passes, and the *resolved* backend beside it.

    ``config.alignment.similarity`` is what was asked for -- ``"auto"`` by
    default -- and ``config.similarity`` is what ran, because "auto picked
    difflib" and "difflib was demanded" are different facts (#143 needs both).
    """
    alignment = AlignmentConfig(similarity="difflib", fuzzy_min_similarity=0.7)
    result = compare(SOURCE_TEXT, TEST_TEXT, format="text", alignment=alignment)
    assert result.config.alignment is alignment
    assert result.config.alignment.similarity == "difflib"
    assert result.config.similarity == "difflib"
    assert result.config.processor == "WholeDocumentProcessor"
    assert result.config.budget_exhausted is False
    assert result.config.to_dict()["alignment"]["fuzzy_min_similarity"] == 0.7


def test_a_custom_processor_is_used_and_named() -> None:
    """R17: the leaf differ is pluggable, and the payload says one was plugged in.

    The name is ``type(processor).__name__`` -- a name, not a serialised
    object -- and the ops on the node are the custom differ's, not the
    default's.
    """
    result = compare(
        SOURCE_TEXT, TEST_TEXT, format="text", processor=WholeBlockProcessor()
    )
    assert result.config.processor == "WholeBlockProcessor"
    assert [str(change.kind) for change in result.changes] == ["modify"]
    assert [op.source_text for op in result.changes[0].inline] == [
        "The Supplier responds within four hours."
    ]
    default = compare(SOURCE_TEXT, TEST_TEXT, format="text")
    assert default.config.processor == "WholeDocumentProcessor"
    assert [op.source_text for op in default.changes[0].inline] == ["four "]


def test_the_alignment_is_public_and_carries_the_unchanged_pairs() -> None:
    """The correspondence set is not expressible in the change tree (ADR-0033).

    An unchanged matched pair produces no change node, so the benchmark reads
    it here or nowhere.
    """
    result = compare(SOURCE_TEXT, TEST_TEXT, format="text")
    assert len(result.alignment.pairs) > len(result.changes)
    assert result.alignment.pass_counts["root"] == 1


# --- the wire shape --------------------------------------------------------


def test_the_document_has_the_v2_top_level_keys() -> None:
    """ADR-0033's shape, in the authored key order, with `source`/`test` untouched.

    The two block-tree sections are byte-for-byte
    `redlines.blocks.BlockTree.to_dict` output: M1's serialisation is not
    reshaped, so an M1 golden stays valid as a slice of a v2 document.
    """
    result = compare(SOURCE_TEXT, TEST_TEXT, format="text")
    payload = result.to_dict()
    assert list(payload) == [
        "schema_version",
        "config",
        "source",
        "test",
        "changes",
    ]
    assert payload["schema_version"] == SCHEMA_VERSION == "2.0"
    assert payload["source"] == result.source.to_dict()
    assert payload["test"] == result.test.to_dict()
    assert [change["kind"] for change in payload["changes"]] == ["modify"]


def test_the_alignment_is_off_the_wire_unless_it_is_asked_for() -> None:
    """Optional, because only the benchmark reads it and it doubles a payload."""
    result = compare(SOURCE_TEXT, TEST_TEXT, format="text")
    assert "alignment" not in result.to_dict()
    with_alignment = result.to_dict(include_alignment=True)
    assert with_alignment["alignment"] == result.alignment.to_dict()


def test_a_comparison_round_trips_through_from_dict() -> None:
    """With its alignment, which is a field of the class and not optional in Python."""
    result = compare(SOURCE_TEXT, TEST_TEXT, format="text")
    payload = result.to_dict(include_alignment=True)
    rebuilt = Comparison.from_dict(payload)
    assert rebuilt.source == result.source
    assert rebuilt.test == result.test
    assert rebuilt.config == result.config
    # Equal on the wire rather than in memory: every ratio is rounded to four
    # places at the serialisation boundary, so a rebuilt comparison carries
    # the rounded confidence and re-serialises to the same bytes.
    assert rebuilt.to_dict(include_alignment=True) == payload


def test_a_payload_written_without_its_alignment_says_so() -> None:
    """Rebuilding it as empty would be a lie about which blocks correspond."""
    result = compare(SOURCE_TEXT, TEST_TEXT, format="text")
    with pytest.raises(ValueError, match="include_alignment=True"):
        Comparison.from_dict(result.to_dict())


@pytest.mark.parametrize(
    ("version", "complaint"),
    [
        (None, "missing the key 'schema_version'"),
        ("2", "not a 'major.minor' version string"),
        ("3.0", "reads 2.x only"),
        ("2.9", "newer than the 2.0"),
    ],
)
def test_a_version_this_release_cannot_read_is_refused(
    version: str | None, complaint: str
) -> None:
    """ADR-0011's policy, enforced on the way in.

    A higher *minor* is rejected rather than silently narrowed: the fields a
    newer release added would be dropped without a word, and the strict key
    checking would otherwise report them as a typo.
    """
    result = compare(SOURCE_TEXT, TEST_TEXT, format="text")
    payload = result.to_dict(include_alignment=True)
    if version is None:
        del payload["schema_version"]
    else:
        payload["schema_version"] = version
    with pytest.raises(ValueError, match=complaint):
        Comparison.from_dict(payload)


def test_an_older_minor_version_is_still_readable() -> None:
    """The other half of the policy: additive means the old shape keeps working."""
    result = compare(SOURCE_TEXT, TEST_TEXT, format="text")
    payload = result.to_dict(include_alignment=True)
    payload["schema_version"] = "2.0"
    assert Comparison.from_dict(payload).config == result.config


def test_to_json_is_to_dict_and_nothing_else() -> None:
    """The convenience, kept honest: no reordering, no escaping of real characters."""
    result = compare("The Supplier — one.", "The Supplier — two.", format="text")
    assert json.loads(result.to_json()) == result.to_dict()
    assert "—" in result.to_json()
    assert "\n" in result.to_json(indent=2)


def test_a_config_round_trips_through_from_dict() -> None:
    """Including the alignment configuration it embeds whole."""
    result = compare(SOURCE_TEXT, TEST_TEXT, format="text")
    assert ComparisonConfig.from_dict(result.config.to_dict()) == result.config
    with pytest.raises(ValueError, match="comparison config has unknown key"):
        ComparisonConfig.from_dict({**result.config.to_dict(), "spam": 1})


# --- determinism (#135) ----------------------------------------------------


def test_comparing_the_same_pair_twice_gives_the_same_json() -> None:
    """In one process first: the cheap half of the promise."""
    first = compare(SOURCE_TEXT, TEST_TEXT, format="text")
    second = compare(SOURCE_TEXT, TEST_TEXT, format="text")
    assert first.to_json(include_alignment=True) == second.to_json(
        include_alignment=True
    )


def test_the_change_tree_is_the_same_under_every_hash_seed() -> None:
    """The half a single process cannot see (#135).

    ``str.__hash__`` is seeded per process, so a stray ``set`` iteration is
    consistent *within* one run and differs *between* runs. This compares the
    sample pair in five subprocesses and diffs their output byte for byte.
    """
    script = (
        "import json, pathlib\n"
        "from redlines import compare\n"
        "case = pathlib.Path('tests/corpus/sample_pair')\n"
        "result = compare(\n"
        "    (case / 'source.md').read_text(encoding='utf-8'),\n"
        "    (case / 'test.md').read_text(encoding='utf-8'),\n"
        "    format='markdown',\n"
        "    profile='markdown',\n"
        ")\n"
        "print(json.dumps(result.to_dict(include_alignment=True), "
        "sort_keys=True, ensure_ascii=False))\n"
    )
    output = assert_byte_identical_across_hash_seeds(script, cwd=REPO_ROOT)
    assert json.loads(output)["schema_version"] == SCHEMA_VERSION


def test_the_sample_pair_compares_through_the_public_entry_point() -> None:
    """One end-to-end run, so the four stages are known to be wired together."""
    result = compare(
        (CASE_DIR / "source.md").read_text(encoding="utf-8"),
        (CASE_DIR / "test.md").read_text(encoding="utf-8"),
        source_path="source.md",
        test_path="test.md",
    )
    assert isinstance(result.source, BlockTree)
    assert isinstance(result.source.root, Block)
    assert result.source.root.kind is BlockKind.DOCUMENT
    assert result.config.profile == "markdown"
    assert len(result.changes) == 10
