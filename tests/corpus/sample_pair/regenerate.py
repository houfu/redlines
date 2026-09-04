"""Regenerate the expected block trees for the PRD § 3a sample pair (#108).

Run this only when a tree change is intentional, then read the diff::

    uv run python tests/corpus/sample_pair/regenerate.py

Four trees are written under ``expected/``: the plain-text twins read by
`redlines.readers.text.PlainTextReader` under the built-in ``contract``
profile, and the markdown pair read by
`redlines.readers.markdown.MarkdownReader` under ``markdown``, each passed
through `redlines.semantic.apply_semantics` — the whole M1 pipeline, in the
order PRD § 6b sets out. `redlines.pipeline.read_document` is that pipeline,
so this script names the format and the profile and lets it compose the rest.
Each file is ``BlockTree.to_dict()`` as JSON with sorted keys, two-space
indent and a trailing newline.

These are *not* the M0 golden outputs of `tests/corpus/regenerate_goldens.py`,
which renders a redline for every case directory; ``sample_pair`` is listed in
that test's ``NOT_GOLDEN_CASES``. The change tree for this pair is M2's golden,
not this file's.

`tests/test_sample_pair.py` deliberately does *not* call this script's
`build_tree`, and does not use `read_document` either: it spells the reader
and the semantic pass out itself and compares the result with what this script
wrote, so a drift between the two — including one introduced by
`read_document` composing the stages differently — is a test failure rather
than a silently regenerated golden.
"""

from __future__ import annotations

import json
from pathlib import Path

from redlines.blocks import BlockTree
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


def dump(tree: BlockTree) -> str:
    """Serialise ``tree`` the way the goldens are stored."""
    return json.dumps(tree.to_dict(), indent=2, sort_keys=True) + "\n"


def regenerate() -> None:
    EXPECTED_DIR.mkdir(exist_ok=True)
    for input_name, format, profile_name in PAIRINGS:
        tree = build_tree(
            CASE_DIR / input_name, format=format, profile_name=profile_name
        )
        target = expected_path(input_name, profile_name)
        target.write_text(dump(tree), encoding="utf-8")
        print(f"wrote {target.relative_to(CASE_DIR.parent.parent)}")


if __name__ == "__main__":
    regenerate()
