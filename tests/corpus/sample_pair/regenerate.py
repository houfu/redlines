"""Regenerate the expected trees and change trees for the sample pair (#108, #144).

Run this only when a change is intentional, then read the diff::

    uv run python tests/corpus/sample_pair/regenerate.py

Six files are written under ``expected/``: four block trees and, since #144,
the two change-tree goldens.

**The four block trees.** The plain-text twins read by
`redlines.readers.text.PlainTextReader` under the built-in ``contract``
profile, and the markdown pair read by
`redlines.readers.markdown.MarkdownReader` under ``markdown``, each passed
through `redlines.semantic.apply_semantics` — the whole M1 pipeline, in the
order PRD § 6b sets out. `redlines.pipeline.read_document` is that pipeline,
so this script names the format and the profile and lets it compose the rest.
Each file is ``BlockTree.to_dict()`` as JSON with sorted keys, two-space
indent and a trailing newline.

**The two change-tree goldens.** ``expected/change_tree.contract.json`` and
``expected/change_tree.markdown.json`` are the whole JSON v2 document
`redlines.comparison.Comparison.to_dict` emits for the pair -- both block
trees, the change tree, the alignment and the statistics -- one per twin. Two
files rather than one because the twins genuinely diverge at CHANGES.md's
change 6: markdown gets a ``row`` insert inside the deliverables table, and
the plain text, which has no table, an inserted paragraph.

They are written with ``include_alignment=True`` so a golden is a *complete*
comparison: `redlines.comparison.Comparison.from_dict` refuses a payload with
no alignment, and a golden that cannot be read back is a weaker freeze than
one that can.

They are also written under an explicitly named similarity backend
(`GOLDEN_BACKEND`) rather than the ``"auto"`` default. ``auto`` resolves to
``rapidfuzz`` where the ``[fuzzy]`` extra is installed and ``difflib`` where it
is not, and the resolved name goes on the wire in ``config.similarity``, so a
golden generated under ``auto`` would fail on whichever CI leg was not the one
that wrote it. ``difflib`` is the floor PRD § 12 runs the documentation site on
and the backend benchmark/REPORT.md quotes. The two backends agree on every
node of this pair -- `tests/test_sample_pair_change_tree.py` asserts exactly
that -- so naming one costs no coverage.

These are *not* the M0 golden outputs of `tests/corpus/regenerate_goldens.py`,
which renders a redline for every case directory; ``sample_pair`` is listed in
that test's ``NOT_GOLDEN_CASES``.

`tests/test_sample_pair.py` deliberately does *not* call this script's
`build_tree`, and does not use `read_document` either: it spells the reader
and the semantic pass out itself and compares the result with what this script
wrote, so a drift between the two — including one introduced by
`read_document` composing the stages differently — is a test failure rather
than a silently regenerated golden. `tests/test_sample_pair_change_tree.py`
keeps the same discipline for the change-tree goldens: it calls the public
`redlines.comparison.compare` itself rather than this script's
`build_comparison`.
"""

from __future__ import annotations

import json
from pathlib import Path

from redlines.alignment import AlignmentConfig
from redlines.blocks import BlockTree
from redlines.comparison import Comparison, compare
from redlines.pipeline import read_document

CASE_DIR = Path(__file__).parent
EXPECTED_DIR = CASE_DIR / "expected"

# (input file, format, profile name) -> expected/<stem>.<profile>.json
PAIRINGS: tuple[tuple[str, str, str], ...] = (
    ("source.txt", "text", "contract"),
    ("test.txt", "text", "contract"),
    ("source.md", "markdown", "markdown"),
    ("test.md", "markdown", "markdown"),
)

# (source file, test file, format, profile name)
#   -> expected/change_tree.<profile>.json
CHANGE_PAIRINGS: tuple[tuple[str, str, str, str], ...] = (
    ("source.txt", "test.txt", "text", "contract"),
    ("source.md", "test.md", "markdown", "markdown"),
)

GOLDEN_BACKEND: str = "difflib"
"""The similarity backend the change-tree goldens are generated under.

Named rather than left at ``"auto"`` so one golden is correct on every CI leg
— see the module docstring.
"""

GOLDEN_ALIGNMENT: AlignmentConfig = AlignmentConfig(similarity=GOLDEN_BACKEND)
"""`redlines.alignment.DEFAULT_ALIGNMENT` with the backend pinned.

Every threshold is the shipped default: a golden generated under tuned
settings would prove the settings, not the engine.
"""


def build_tree(path: Path, *, format: str, profile_name: str) -> BlockTree:
    """Read ``path`` under ``profile_name`` and run the semantic pass.

    The format and the profile are both named rather than detected, because a
    golden should not move when detection or a default does.

    :param path: one of the four sample-pair input files.
    :param format: the reader format name, ``"text"`` or ``"markdown"``.
    :param profile_name: the built-in profile to read and interpret under.
    :return: the `redlines.blocks.BlockTree` the pair is expected to parse into.
    """
    return read_document(
        path.read_text(encoding="utf-8"), format=format, profile=profile_name
    )


def expected_path(input_name: str, profile_name: str) -> Path:
    """Return the golden path for one input and profile."""
    return EXPECTED_DIR / f"{Path(input_name).stem}.{profile_name}.json"


def build_comparison(
    source_name: str, test_name: str, *, format: str, profile_name: str
) -> Comparison:
    """Compare one twin of the pair, through the public entry point.

    Kept separate from `build_tree` on purpose: that function freezes what M1
    *reads*, this one freezes what M2 *makes of the difference*, and the two
    move for different reasons.

    :param source_name: the earlier document's file name in this directory.
    :param test_name: the later one's.
    :param format: the reader format name, ``"text"`` or ``"markdown"``.
    :param profile_name: the built-in profile both sides are read under.
    :return: the `redlines.comparison.Comparison` this twin is expected to
        produce, under `GOLDEN_ALIGNMENT`.
    """
    return compare(
        (CASE_DIR / source_name).read_text(encoding="utf-8"),
        (CASE_DIR / test_name).read_text(encoding="utf-8"),
        format=format,
        profile=profile_name,
        alignment=GOLDEN_ALIGNMENT,
    )


def change_tree_path(profile_name: str) -> Path:
    """Return the change-tree golden path for one profile."""
    return EXPECTED_DIR / f"change_tree.{profile_name}.json"


def dump(tree: BlockTree) -> str:
    """Serialise ``tree`` the way the goldens are stored."""
    return json.dumps(tree.to_dict(), indent=2, sort_keys=True) + "\n"


def dump_comparison(comparison: Comparison) -> str:
    """Serialise ``comparison`` the way the change-tree goldens are stored.

    `redlines.comparison.Comparison.to_json` deliberately keeps the authored
    key order; the goldens want the alphabet, so this calls `json.dumps` on
    ``to_dict()``'s output exactly as `dump` does. Every ratio was already
    rounded to four places at the dataclass boundary (ADR-0033), so nothing
    here touches a number a second time.

    :param comparison: what `build_comparison` returned.
    :return: the JSON text, sorted, two-space indented, newline-terminated.
    """
    return (
        json.dumps(
            comparison.to_dict(include_alignment=True), indent=2, sort_keys=True
        )
        + "\n"
    )


def regenerate() -> None:
    EXPECTED_DIR.mkdir(exist_ok=True)
    for input_name, format, profile_name in PAIRINGS:
        tree = build_tree(
            CASE_DIR / input_name, format=format, profile_name=profile_name
        )
        target = expected_path(input_name, profile_name)
        target.write_text(dump(tree), encoding="utf-8")
        print(f"wrote {target.relative_to(CASE_DIR.parent.parent)}")
    for source_name, test_name, format, profile_name in CHANGE_PAIRINGS:
        comparison = build_comparison(
            source_name, test_name, format=format, profile_name=profile_name
        )
        target = change_tree_path(profile_name)
        target.write_text(dump_comparison(comparison), encoding="utf-8")
        print(
            f"wrote {target.relative_to(CASE_DIR.parent.parent)} "
            f"({len(comparison.changes.changes)} change nodes)"
        )


if __name__ == "__main__":
    regenerate()
