"""The 0.6 `Redlines` class over the core (ADR-0036; M3 decisions D1 and D2).

Byte identity with 0.6.2 comes only from 0.6's own whole-document opcodes, so
the class keeps its 0.6 code for every 0.6 output, and the core's change tree
is derived from those same opcodes on demand by the private
`Redlines._comparison`. This module holds that arrangement to its rules:

- **Nothing new is public.** `Redlines` has exactly v0.6.2's public names, and
  every name ``import redlines`` gave in v0.6.2 is still there. ADR-0003
  freezes public names until 2.0, and a caller who wants structure calls
  `redlines.compare`, which is a different, block-aligned diff.
- **The derived comparison is the core's own data.** It validates against the
  published schema, round-trips through ``to_dict(include_alignment=True)``
  and `Comparison.from_dict`, and holds either no node or one ``modify`` node
  whose inline ops are `inline_ops_from_opcodes` of the very opcodes the 0.6
  outputs render. Each side's one block holds the text exactly as given, and
  the ops index that text, including where one of 0.6's edits runs across a
  paragraph break, which no pair of paragraph blocks could hold.
- **The 0.6 path is still 0.6's.** The processor runs once per assignment and
  never for the derived comparison, which replays what the processor returned.
  The quick path still runs with every import failing, as the pinned
  ``test_advanced_stats_levenshtein_fallback`` requires. Inside a function,
  `redlines/redlines.py` imports only what 0.6 did, and the core modules
  `_comparison()` runs through import nothing at all.
- **The derived comparison is cached** against the identity of the opcode
  list and the two texts, on the instance.
"""

from __future__ import annotations

import ast
import builtins
import json
from collections.abc import Callable, Mapping, Sequence
from difflib import SequenceMatcher
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import jsonschema
import pytest

import redlines
from redlines import Redlines
from redlines import redlines as facade_module
from redlines.alignment import DEFAULT_ALIGNMENT
from redlines.blocks import BlockKind
from redlines.changes import ChangeKind, InlineKind, InlineOp, inline_ops_from_opcodes
from redlines.comparison import Comparison, ComparisonConfig, comparison_schema_text
from redlines.document import Document
from redlines.processor import (
    Chunk,
    DiffOperation,
    RedlinesProcessor,
    WholeDocumentProcessor,
)

PACKAGE_DIR = Path(redlines.__file__).resolve().parent
TESTS_DIR = Path(__file__).resolve().parent
CORPUS = TESTS_DIR / "corpus"
CSA_DIR = TESTS_DIR.parent / "benchmark" / "corpus" / "hand" / "csa-1.1-to-2.0"

# `{n for n in dir(Redlines) if not n.startswith("_")}` for the class in
# `git show v0.6.2:redlines/redlines.py`, computed once against the tag and
# written out, so the check needs neither git nor the tag.
V062_REDLINES_NAMES = frozenset(
    {
        "changes",
        "compare",
        "get_changes",
        "opcodes",
        "output_json",
        "output_markdown",
        "output_rich",
        "redlines",
        "source",
        "stats",
        "test",
    }
)

# Every public name of the `redlines` package at v0.6.2: `dir(redlines)`
# without the underscore names, including the five submodules its
# `__init__.py` imported. Computed against the tag the same way.
V062_PACKAGE_NAMES = frozenset(
    {
        "Chunk",
        "DiffOperation",
        "Document",
        "MarkdownStyle",
        "NupunktProcessor",
        "OutputType",
        "PDFFile",
        "PDFPage",
        "PDF_AVAILABLE",
        "PlainTextFile",
        "Redline",
        "Redlines",
        "RedlinesOptions",
        "RedlinesProcessor",
        "Stats",
        "WholeDocumentProcessor",
        "document",
        "enums",
        "pdf",
        "processor",
        "redlines",
    }
)

# The modules `_comparison()` runs through, plus the renderers once M3 adds
# them: none of them may import inside a function (D1 rule 4).
CORE_MODULES = sorted(
    [
        PACKAGE_DIR / f"{name}.py"
        for name in (
            "changes",
            "alignment",
            "blocks",
            "processor",
            "similarity",
            "comparison",
            "statistics",
            "filters",
        )
    ]
    + list((PACKAGE_DIR / "renderers").rglob("*.py"))
)


def _text(path: Path) -> str:
    """A file's text, byte for byte: no newline translation."""
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def _pair(case: str) -> tuple[str, str]:
    """Both sides of a case under ``tests/corpus/``."""
    return _text(CORPUS / case / "source.txt"), _text(CORPUS / case / "test.txt")


FOX = (
    "The quick brown fox jumps over the lazy dog.",
    "The quick brown fox walks past the lazy dog.",
)
MULTI_PARAGRAPH = _pair("multi_paragraph")

# Three inputs on which one of 0.6's edits runs from one paragraph into the
# next: the reason the facade is one block per document, not one per paragraph
# (ADR-0036). A constructed pair, the sample pair's text twin, and the largest
# hand pair in the benchmark.
STRADDLE = (
    "1. Alpha clause.\n\n2. Beta clause.\n\n3. Gamma.",
    "1. Alpha clause.\n\n3. Gamma.\n\n2. Beta clause amended.",
)
SAMPLE_PAIR = _pair("sample_pair")
CSA = (_text(CSA_DIR / "source.md"), _text(CSA_DIR / "test.md"))


class CharacterProcessor(RedlinesProcessor):
    """A custom processor (R17): every character is a token, diffed by difflib.

    It imports nothing when it runs, so it can stand in the import-patch tests
    beside the default processor.
    """

    def process(
        self, source: Document | str, test: Document | str
    ) -> list[DiffOperation]:
        source_tokens = list(source.text if isinstance(source, Document) else source)
        test_tokens = list(test.text if isinstance(test, Document) else test)
        matcher = SequenceMatcher(None, source_tokens, test_tokens, autojunk=False)
        return [
            DiffOperation(
                source_chunk=Chunk(text=source_tokens, chunk_location=None),
                test_chunk=Chunk(text=test_tokens, chunk_location=None),
                opcodes=opcode,
            )
            for opcode in matcher.get_opcodes()
        ]


class CountingProcessor(RedlinesProcessor):
    """The default processor, counting how often it is asked to diff."""

    def __init__(self) -> None:
        self.calls = 0
        self._inner = WholeDocumentProcessor()

    def process(
        self, source: Document | str, test: Document | str
    ) -> list[DiffOperation]:
        self.calls += 1
        return self._inner.process(source, test)


class ReusingProcessor(RedlinesProcessor):
    """A custom processor that refills and returns one list object every time."""

    def __init__(self) -> None:
        self._buffer: list[DiffOperation] = []
        self._inner = WholeDocumentProcessor()

    def process(
        self, source: Document | str, test: Document | str
    ) -> list[DiffOperation]:
        self._buffer[:] = self._inner.process(source, test)
        return self._buffer


class InMemoryDocument(Document):
    """The smallest `redlines.document.Document`: a string, held in memory."""

    def __init__(self, text: str) -> None:
        self._text = text

    @property
    def text(self) -> str:
        return self._text


def _read_every_output(r: Redlines) -> None:
    """Read every 0.6 output once, the way a 0.6 caller would."""
    outputs = (
        r.opcodes,
        r.changes,
        r.redlines,
        r.get_changes(),
        r.stats(),
        r.output_markdown,
        r.output_rich,
        r.output_json(),
        r.compare(),
    )
    assert len(outputs) == 9


@pytest.fixture(scope="module")
def validator() -> jsonschema.protocols.Validator:
    """The published comparison schema, checked and compiled once."""
    schema = json.loads(comparison_schema_text())
    jsonschema.Draft7Validator.check_schema(schema)
    return jsonschema.Draft7Validator(schema)


# --- nothing new is public (D2) ----------------------------------------------


def test_redlines_has_exactly_the_public_names_of_v062() -> None:
    """The facade adds no public name: `_comparison()` stays private (D2)."""
    assert {name for name in dir(Redlines) if not name.startswith("_")} == (
        V062_REDLINES_NAMES
    )


def test_v062_names_still_exported() -> None:
    """Every name ``import redlines`` gave in v0.6.2 is still importable from it."""
    assert sorted(V062_PACKAGE_NAMES - set(dir(redlines))) == []


def test_the_docstring_points_structural_callers_at_compare() -> None:
    """The one place a 0.6 caller learns where the structural view is (D2)."""
    assert "redlines.compare(self.source, self.test)" in (Redlines.__doc__ or "")


# --- the derived comparison is the core's own data (D1) ----------------------


@pytest.mark.parametrize(
    ("source", "test", "nodes"),
    [
        # The seven M0 golden cases, all under the default processor: what is
        # checked here is the derivation, not the goldens.
        pytest.param(*FOX, 1, id="readme_fox"),
        pytest.param(*_pair("course_lesson6"), 1, id="course_lesson6"),
        pytest.param(*MULTI_PARAGRAPH, 1, id="multi_paragraph"),
        pytest.param(*_pair("punctuation_merge"), 1, id="punctuation_merge"),
        pytest.param(*_pair("repetitive_schedule"), 1, id="repetitive_schedule"),
        pytest.param(*_pair("sentence_paragraphs"), 1, id="sentence_paragraphs"),
        pytest.param(*_pair("whitespace_after_equal"), 1, id="whitespace_after_equal"),
        # An edit across a paragraph break.
        pytest.param(*STRADDLE, 1, id="constructed_straddle"),
        pytest.param(*SAMPLE_PAIR, 1, id="sample_pair"),
        pytest.param(*CSA, 1, id="csa_1_1_to_2_0"),
        # Text that a reader or a careless facade would normalise.
        pytest.param("  Hello world \n", "  Hello there \n", 1, id="padded"),
        pytest.param("a\r\nb\r\n\r\nc", "a\r\nb\r\n\r\nd", 1, id="crlf"),
        pytest.param(MULTI_PARAGRAPH[0], MULTI_PARAGRAPH[0], 0, id="identical"),
        pytest.param("", "", 0, id="empty"),
        pytest.param("", "Hello", 1, id="insert_into_empty"),
        pytest.param("Hello", "", 1, id="delete_to_empty"),
        pytest.param("Hello world\n", "Hello world", 0, id="whitespace_only"),
    ],
)
def test_the_derived_comparison_is_valid_core_data(
    validator: jsonschema.protocols.Validator, source: str, test: str, nodes: int
) -> None:
    """Schema-valid, round-trips, and holds exactly the edits `changes` reports.

    No node when the processor found no edit -- identical texts never reach
    it, and a whitespace-only difference gives it nothing to report -- and
    otherwise one ``modify`` node whose inline ops are the recorded opcodes in
    characters, slicing the texts exactly as they were given.
    """
    r = Redlines(source, test)
    comparison = r._comparison()

    # Not stripped, not re-joined, not normalised: the text the processor saw.
    assert [block.text for block in comparison.source.root.children] == [source]
    assert [block.text for block in comparison.test.root.children] == [test]

    document = comparison.to_dict(include_alignment=True)
    validator.validate(document)
    assert Comparison.from_dict(document) == comparison

    expected = inline_ops_from_opcodes(r._diff_ops, source_text=source, test_text=test)
    changes = list(comparison.changes)
    assert len(changes) == nodes
    if expected:
        (change,) = changes
        assert change.kind is ChangeKind.MODIFY
        assert change.inline == expected
        assert (change.source_address, change.test_address) == (
            "/paragraph[1]",
            "/paragraph[1]",
        )
        _assert_slices_of(change.inline, source, test)
    else:
        assert changes == []


def _assert_slices_of(ops: Sequence[InlineOp], source: str, test: str) -> None:
    """Every op is an in-order slice of the two texts exactly as given."""
    source_at = test_at = 0
    for op in ops:
        assert source_at <= op.source_start <= op.source_end <= len(source)
        assert test_at <= op.test_start <= op.test_end <= len(test)
        assert source[op.source_start : op.source_end] == op.source_text
        assert test[op.test_start : op.test_end] == op.test_text
        if op.kind is InlineKind.INSERT:
            assert op.source_text == ""
        if op.kind is InlineKind.DELETE:
            assert op.test_text == ""
        source_at, test_at = op.source_end, op.test_end


@pytest.mark.parametrize(
    ("source", "test"),
    [
        pytest.param(*STRADDLE, id="constructed_straddle"),
        pytest.param(*SAMPLE_PAIR, id="sample_pair"),
        pytest.param(*CSA, id="csa_1_1_to_2_0"),
    ],
)
def test_one_block_holds_an_edit_that_crosses_a_paragraph_break(
    source: str, test: str
) -> None:
    """The facade's reason to exist (ADR-0036).

    0.6 diffs the whole document at once, so one of its edits can run from
    one paragraph into the next: 0.6 itself reports a change with a paragraph
    marker inside it. No pair of paragraph blocks could hold that edit. The
    one block a side does, as an inline op that crosses a blank line and still
    slices the texts as given.
    """
    r = Redlines(source, test)
    assert any(
        "\N{PILCROW SIGN}" in text.strip("\N{PILCROW SIGN} ")
        for change in r.changes
        for text in (change.source_text or "", change.test_text or "")
    )

    (change,) = r._comparison().changes
    crossing = [
        op
        for op in change.inline
        if "\n\n" in op.source_text.strip() or "\n\n" in op.test_text.strip()
    ]
    assert crossing
    _assert_slices_of(crossing, source, test)


def test_the_derived_comparison_says_how_it_was_made() -> None:
    """One paragraph a side holding the text as given, a stated alignment, no reader."""
    r = Redlines(*MULTI_PARAGRAPH)
    comparison = r._comparison()

    for tree, text in ((comparison.source, r.source), (comparison.test, r.test)):
        assert tree.root.kind is BlockKind.DOCUMENT
        (paragraph,) = tree.root.children
        assert (paragraph.kind, paragraph.path, paragraph.text) == (
            BlockKind.PARAGRAPH,
            "/paragraph[1]",
            text,
        )
    alignment = comparison.alignment
    assert [
        (pair.source_path, pair.test_path, pair.matched_by, pair.confidence)
        for pair in alignment.pairs
    ] == [
        ("/", "/", "root", 1.0),
        ("/paragraph[1]", "/paragraph[1]", "positional", 1.0),
    ]
    assert (alignment.inserted, alignment.deleted) == ((), ())
    assert alignment.config == DEFAULT_ALIGNMENT
    assert alignment.backend == "difflib"
    assert {name: n for name, n in alignment.pass_counts.items() if n} == {
        "root": 1,
        "positional": 1,
    }
    assert comparison.config == ComparisonConfig(
        source_format="blocks",
        test_format="blocks",
        profile="",
        alignment=DEFAULT_ALIGNMENT,
        similarity="difflib",
        processor="WholeDocumentProcessor",
    )


def test_a_custom_processor_is_replayed_like_the_default(
    validator: jsonschema.protocols.Validator,
) -> None:
    """R17: the derived comparison reads a custom processor's opcodes the same way."""
    r = Redlines(*FOX, processor=CharacterProcessor())
    comparison = r._comparison()

    validator.validate(comparison.to_dict(include_alignment=True))
    assert comparison.config.processor == "CharacterProcessor"
    (change,) = comparison.changes
    assert change.inline == inline_ops_from_opcodes(
        r._diff_ops, source_text=r.source, test_text=r.test
    )


def test_the_derived_comparison_replays_the_recorded_opcodes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The builder gets the instance's own opcode list, once, for the recorded texts."""
    replayed: list[tuple[Document | str, Document | str, list[DiffOperation]]] = []
    replay = facade_module._ReplayProcessor.process

    def spy(
        self: facade_module._ReplayProcessor,
        source: Document | str,
        test: Document | str,
    ) -> list[DiffOperation]:
        diff_operations = replay(self, source, test)
        replayed.append((source, test, diff_operations))
        return diff_operations

    monkeypatch.setattr(facade_module._ReplayProcessor, "process", spy)

    r = Redlines(*MULTI_PARAGRAPH)
    r._comparison()
    assert len(replayed) == 1
    source, test, diff_operations = replayed[0]
    assert (source, test) == MULTI_PARAGRAPH
    assert diff_operations is r._diff_ops

    replayed.clear()
    Redlines(MULTI_PARAGRAPH[0], MULTI_PARAGRAPH[0])._comparison()
    assert replayed == []


def test_the_replay_refuses_texts_it_did_not_record() -> None:
    """A replay asked about another pair is a bug, and says so rather than guessing."""
    r = Redlines(*FOX)
    replay = facade_module._ReplayProcessor(r.source, r.test, r._diff_ops)
    assert replay.process(r.source, r.test) is r._diff_ops
    assert (
        replay.process(InMemoryDocument(r.source), InMemoryDocument(r.test))
        is r._diff_ops
    )
    with pytest.raises(AssertionError, match="different pair"):
        replay.process(r.source, "The quick brown fox sleeps.")
    with pytest.raises(AssertionError, match="different pair"):
        replay.process("The quick brown fox sleeps.", r.test)


# --- the 0.6 path is still 0.6's (D1) ----------------------------------------


def test_the_processor_runs_once_per_assignment_and_not_for_the_comparison() -> None:
    """Where 0.6 ran it: in the setters, once each, and not again for any reader."""
    counting = CountingProcessor()
    r = Redlines(*MULTI_PARAGRAPH, processor=counting)
    assert counting.calls == 1

    _read_every_output(r)
    r._comparison()
    r._comparison()
    r.compare(MULTI_PARAGRAPH[1])  # the same test text: 0.6 does not diff it again
    assert counting.calls == 1

    r.test = FOX[1]
    assert counting.calls == 2
    r._comparison()
    assert counting.calls == 2

    r.source = FOX[0]
    assert counting.calls == 3
    _read_every_output(r)
    r._comparison()
    assert counting.calls == 3


# nupunkt is not among these inputs: its own `load()` imports at call time
# (`from nupunkt.utils.compression import ...`), so with every import failing
# even the unmodified 0.6 class raises under `NupunktProcessor` (critic S10).
QUICK_PATH_CASES = [
    pytest.param(*MULTI_PARAGRAPH, WholeDocumentProcessor, id="multi_paragraph"),
    pytest.param(*MULTI_PARAGRAPH, CharacterProcessor, id="custom_processor"),
]


@pytest.mark.parametrize(("source", "test", "make_processor"), QUICK_PATH_CASES)
def test_the_quick_path_runs_with_every_import_failing(
    source: str, test: str, make_processor: Callable[[], RedlinesProcessor]
) -> None:
    """The twin of the pinned ``test_advanced_stats_levenshtein_fallback``.

    The same blanket patch, over more of the quick path and two processors.
    `_comparison()` is read once the patch is lifted: it is not on that path.
    """
    processor = make_processor()
    with patch.dict("sys.modules", {"Levenshtein": None}):
        with patch(
            "builtins.__import__",
            side_effect=ImportError("no import may run on the 0.6 quick path"),
        ):
            r = Redlines(source, test, processor=processor)
            stats = r.stats()
            markdown = r.output_markdown
            opcodes = r.opcodes
            changes = r.changes

    assert stats.levenshtein_distance is None
    assert stats.total_changes == len(changes) > 0
    assert opcodes == [diff_op.opcodes for diff_op in r._diff_ops]
    assert (
        markdown == Redlines(source, test, processor=make_processor()).output_markdown
    )

    comparison = r._comparison()
    assert [change.kind for change in comparison.changes] == [ChangeKind.MODIFY]


def _refusing_redlines_imports(
    real_import: Callable[..., ModuleType],
) -> Callable[..., ModuleType]:
    """An ``__import__`` that fails any import statement run by redlines' own code."""

    def guarded(
        name: str,
        globals: Mapping[str, object] | None = None,
        locals: Mapping[str, object] | None = None,
        fromlist: Sequence[str] = (),
        level: int = 0,
    ) -> ModuleType:
        importer = (globals or {}).get("__name__")
        if isinstance(importer, str) and importer.split(".")[0] == "redlines":
            raise ImportError(f"{importer} imports {name!r} when called")
        return real_import(name, globals, locals, fromlist, level)

    return guarded


@pytest.mark.parametrize(
    ("source", "test", "make_processor", "nodes"),
    [
        pytest.param(*MULTI_PARAGRAPH, WholeDocumentProcessor, 1, id="multi_paragraph"),
        pytest.param(*MULTI_PARAGRAPH, CharacterProcessor, 1, id="custom_processor"),
        pytest.param(
            MULTI_PARAGRAPH[0],
            MULTI_PARAGRAPH[0],
            WholeDocumentProcessor,
            0,
            id="identical",
        ),
        pytest.param("", "", WholeDocumentProcessor, 0, id="empty"),
    ],
)
def test_nothing_redlines_runs_imports_when_called(
    source: str,
    test: str,
    make_processor: Callable[[], RedlinesProcessor],
    nodes: int,
) -> None:
    """The selective twin: only redlines' own import statements fail (D1 rule 4).

    Third-party code keeps its call-time imports, so the derived comparison
    and `output_rich` can run inside the patch. `output_json` is left out: its
    ``import json`` is one of the three call-time imports 0.6 already had.
    """
    processor = make_processor()
    with patch("builtins.__import__", _refusing_redlines_imports(builtins.__import__)):
        r = Redlines(source, test, processor=processor)
        stats = r.stats()
        outputs = (r.changes, r.opcodes, r.output_markdown, r.output_rich)
        comparison = r._comparison()

    assert stats.levenshtein_distance is None  # its guarded import was refused
    assert len(outputs) == 4
    assert len(comparison.changes) == nodes


def _function_local_imports(path: Path) -> list[tuple[str, str]]:
    """Every import statement inside a function body, as (function, statement).

    A module-level ``try:`` or ``if TYPE_CHECKING:`` import runs at import
    time, not when something is called, so it is not one of these.
    """
    found: list[tuple[str, str]] = []

    def visit(node: ast.AST, function: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, child.name)
            elif isinstance(child, (ast.Import, ast.ImportFrom)) and function:
                found.append((function, ast.unparse(child)))
            else:
                visit(child, function)

    visit(ast.parse(path.read_text(encoding="utf-8")), None)
    return found


def test_the_facade_imports_at_call_time_only_what_0_6_did() -> None:
    """Two guarded ``import Levenshtein`` in `stats`, ``import json`` in `output_json`.

    Anything else would run inside the pinned import-patching test and fail it
    far from its cause (A6).
    """
    assert sorted(_function_local_imports(PACKAGE_DIR / "redlines.py")) == [
        ("output_json", "import json"),
        ("stats", "import Levenshtein"),
        ("stats", "import Levenshtein"),
    ]


@pytest.mark.parametrize("path", CORE_MODULES, ids=lambda path: path.name)
def test_the_core_has_no_function_local_imports(path: Path) -> None:
    """The modules `_comparison()` runs through import everything at module top."""
    assert _function_local_imports(path) == []


# --- the derived comparison is cached (D1) -----------------------------------


def test_the_derived_comparison_needs_a_comparison_first() -> None:
    """Before there is a test text it raises 0.6's own error, like every output."""
    r = Redlines("Only a source.")
    with pytest.raises(ValueError, match="No diff operations available"):
        r._comparison()
    r.test = "Only a source, and now a test."
    assert [change.kind for change in r._comparison().changes] == [ChangeKind.MODIFY]


def test_the_derived_comparison_is_cached_until_a_setter_runs() -> None:
    """Kept against the opcode list the setters assign; a new list is a new one."""
    r = Redlines(*MULTI_PARAGRAPH)
    first = r._comparison()
    assert r._comparison() is first

    _read_every_output(r)
    r.compare(MULTI_PARAGRAPH[1])  # the same test text skips the setter in 0.6
    r.compare(markdown_style="none")  # options do not touch the opcodes
    assert r._comparison() is first

    r.test = MULTI_PARAGRAPH[1]  # the setter diffs again, even for the same text
    second = r._comparison()
    assert second is not first
    assert second == first

    r.test = FOX[1]
    third = r._comparison()
    assert third.test.root.children[0].text == FOX[1]
    assert third.source.root.children[0].text == MULTI_PARAGRAPH[0]

    r.source = FOX[0]
    fourth = r._comparison()
    assert fourth is not third
    assert fourth.source.root.children[0].text == FOX[0]
    assert r._comparison() is fourth


def test_one_list_object_for_new_texts_still_derives_again() -> None:
    """The cache compares both texts as well as the list's identity.

    A processor may refill and return the same list object from every call.
    The setter then leaves `_diff_operations` the very same object, and only
    the texts tell the cache that what it holds is a comparison of others.
    """
    r = Redlines(*FOX, processor=ReusingProcessor())
    first = r._comparison()
    recorded = r._diff_operations

    r.test = "An entirely different sentence."
    assert r._diff_operations is recorded  # the premise: one list, refilled
    second = r._comparison()
    assert second is not first
    assert second.test.root.children[0].text == r.test
    (change,) = second.changes
    assert change.inline == inline_ops_from_opcodes(
        r._diff_ops, source_text=r.source, test_text=r.test
    )

    r.source = "A different source altogether."
    assert r._diff_operations is recorded
    third = r._comparison()
    assert third is not second
    assert third.source.root.children[0].text == r.source


def test_two_instances_do_not_share_a_cache() -> None:
    """The cache lives on the instance; the class attribute is only its default."""
    a = Redlines(*FOX)
    first = a._comparison()
    Redlines(*FOX)._comparison()  # a second instance derives and keeps its own
    assert a._comparison() is first
