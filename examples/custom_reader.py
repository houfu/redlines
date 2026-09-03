#!/usr/bin/env python3
"""
A third-party reader, written the way you would write your own (PRD R7).

Nothing here subclasses anything from redlines. `redlines.readers.Reader` is a
`typing.Protocol`: a class with a ``name``, a ``formats`` tuple and a ``read``
method *is* a reader, and `register_reader` puts it where `reader_for` can
find it. Registering an extension with `redlines.readers.detect` means format
detection knows about it too.

The format read here is a made-up line-oriented one, a "clause file", chosen
because it is small enough to read in one sitting and real enough to exercise
every part of the block model:

    # lines starting with a hash are comments
    TITLE: Master Services Agreement
    SECTION: 1. Interpretation
    CLAUSE: 1.1 In this agreement, "Services" means the services in Schedule 1.
    An untagged line is a plain paragraph.
    UNSUPPORTED: a tag the reader does not know is dropped, and reported.

One record per line, ``TAG: text``. ``TITLE`` and ``SECTION`` carry headings,
``SECTION`` opens a section that following ``CLAUSE`` records nest inside,
``NOTE`` is a note, an untagged line is a paragraph nothing recognised, and an
unknown tag is dropped and disclosed (R3).

Usage:
    python custom_reader.py              # read the built-in sample
    python custom_reader.py deal.clf     # read a clause file of your own
"""

from __future__ import annotations

import re
import sys
from dataclasses import replace
from pathlib import Path

from redlines.blocks import (
    MATCHED_BY_DOCUMENT,
    MATCHED_BY_FALLBACK,
    Block,
    BlockKind,
    BlockTree,
    Dropped,
)
from redlines.profiles import Profile
from redlines.readers import (
    DEFAULT_MAX_CHARS,
    Reader,
    check_size,
    decode_source,
    reader_for,
    readers,
    register_reader,
)
from redlines.readers.detect import detect_format, register_extension

SAMPLE = """\
# A clause file. One record per line, "TAG: text".
TITLE: Master Services Agreement

SECTION: 1. Interpretation
CLAUSE: 1.1 In this agreement, "Services" means the services described in Schedule 1.
CLAUSE: 1.2 Headings are for convenience and do not affect interpretation.
NOTE: Clause 1.2 is standard and was not negotiated.

SECTION: 2. Term
CLAUSE: 2.1 This agreement starts on the Commencement Date.
CLAUSE: 2.2 Either party may terminate on thirty (30) days' written notice.
This line carries no tag, so nothing recognises it.
SIGNATURE_IMAGE: a tag this reader does not know
"""

# "1.", "1.1", "2.3.4" at the start of a record: the file's own label.
LABEL = re.compile(r"^(?P<label>\d+(?:\.\d+)*)\.?\s+(?P<rest>\S.*)$")
RECORD = re.compile(r"^(?P<tag>[A-Z][A-Z_]*):\s*(?P<text>.*)$")


def split_label(text: str) -> tuple[str | None, str]:
    """Split a leading numeric label off a record's text.

    :param text: one record's text, label and all.
    :return: the label (or ``None``) and the text without it.
    """
    match = LABEL.match(text)
    if match is None:
        return None, text
    return match["label"], match["rest"]


class ClauseFileReader:
    """Reads the clause file format into a `redlines.blocks.BlockTree`.

    This class is the whole contract: three members, no inheritance, no
    registration hook, no entry point. ``isinstance(ClauseFileReader(),
    Reader)`` is true because the members are there.

    Because the format states its own structure, every block it recognises is
    reported with ``confidence`` 1.0 and a ``matched_by`` in its own
    ``clause-file:<TAG>`` family -- the family names in
    `redlines.blocks.MATCHED_BY_FAMILIES` are a recommendation for readers
    that infer structure, not a closed list. The one thing this reader does
    *not* recognise, an untagged line, gets ``fallback`` and 0.0, which is the
    same answer every reader in redlines gives when nothing matches.
    """

    name = "clause-file"
    formats = ("clause-file",)

    def read(
        self,
        source: str | bytes,
        *,
        profile: Profile | None = None,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> BlockTree:
        """Read a clause file.

        :param source: the file's content, as text or UTF-8 bytes.
        :param profile: unused: this format declares its own structure, so
            there is nothing for a profile to detect. A reader that infers
            structure would read its label patterns from here instead.
        :param max_chars: the input size cap every reader applies (ADR-0028).
        :return: the document as an addressed tree, with unknown tags
            reported in ``dropped``.
        """
        text = decode_source(source, reader=self.name)
        check_size(text, max_chars=max_chars, reader=self.name)

        top: list[Block] = []
        open_section: Block | None = None
        section_children: list[Block] = []
        unknown_tags: dict[str, int] = {}

        def emit(block: Block) -> None:
            """Add a block to the open section, or to the document itself."""
            (section_children if open_section is not None else top).append(block)

        def close_section() -> None:
            """Rebuild the open section with the children it collected.

            Blocks are frozen and their children are a tuple, so a container
            is built once its contents are known -- which is why a reader
            collects children in a list and only then makes the block.
            """
            nonlocal open_section
            if open_section is not None:
                top.append(replace(open_section, children=tuple(section_children)))
                open_section = None
                section_children.clear()

        for line in text.replace("\r\n", "\n").split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            record = RECORD.match(stripped)
            if record is None:
                emit(
                    Block(
                        kind=BlockKind.PARAGRAPH,
                        text=stripped,
                        matched_by=MATCHED_BY_FALLBACK,
                        confidence=0.0,
                    )
                )
                continue

            tag, body = record["tag"], record["text"].strip()
            label, rest = split_label(body)
            matched_by = f"{self.name}:{tag}"

            if tag == "TITLE":
                emit(
                    Block(
                        kind=BlockKind.HEADING,
                        text=body,
                        role="title",
                        matched_by=matched_by,
                        confidence=1.0,
                    )
                )
            elif tag == "SECTION":
                close_section()
                open_section = Block(
                    kind=BlockKind.SECTION,
                    label=label,
                    level=1,
                    matched_by=matched_by,
                    confidence=1.0,
                )
                section_children.append(
                    Block(
                        kind=BlockKind.HEADING,
                        text=rest,
                        label=label,
                        level=1,
                        matched_by=matched_by,
                        confidence=1.0,
                    )
                )
            elif tag == "CLAUSE":
                emit(
                    Block(
                        kind=BlockKind.LIST_ITEM,
                        text=rest,
                        label=label,
                        level=len(label.split(".")) if label else 1,
                        role="clause",
                        matched_by=matched_by,
                        confidence=1.0,
                    )
                )
            elif tag == "NOTE":
                emit(
                    Block(
                        kind=BlockKind.PARAGRAPH,
                        text=body,
                        role="note",
                        matched_by=matched_by,
                        confidence=1.0,
                    )
                )
            else:
                unknown_tags[tag] = unknown_tags.get(tag, 0) + 1

        close_section()

        root = Block(
            kind=BlockKind.DOCUMENT,
            matched_by=MATCHED_BY_DOCUMENT,
            confidence=1.0,
            attrs={"reader": self.name},
            children=tuple(top),
        )
        dropped = tuple(
            Dropped(
                kind="unknown_tag",
                count=count,
                reason=f"{tag!r} is not a clause file record tag, so the line was skipped",
            )
            for tag, count in sorted(unknown_tags.items())
        )
        return BlockTree.build(root, dropped=dropped)


def describe(tree: BlockTree) -> None:
    """Print a tree's addresses, labels and provenance.

    :param tree: the tree to print.
    """
    print("Paths, labels and how each block was recognised:")
    print(f"  {'path':<32} {'label':<6} {'role':<9} {'matched_by':<20} text")
    print("  " + "-" * 100)
    for block in tree.walk():
        text = block.text if len(block.text) <= 34 else block.text[:31] + "..."
        print(
            f"  {block.path:<32} {block.label or '-':<6} {block.role or '-':<9} "
            f"{block.matched_by:<20} {text}"
        )

    print()
    print(f"Blocks: {sum(1 for _ in tree.walk())}")
    print(f"Fallback blocks: {tree.fallback_count}")
    if tree.dropped:
        print("Dropped:")
        for dropped in tree.dropped:
            print(f"  {dropped.kind} x{dropped.count}: {dropped.reason}")
    else:
        print("Dropped: nothing")

    # A breadcrumb is derived from position, so any address in the tree has
    # one; the last labelled block makes the most legible demonstration.
    labelled = [block for block in tree.walk() if block.label]
    if labelled:
        deepest = labelled[-1]
        crumbs = tree.heading_breadcrumb(deepest.path)
        print()
        print(f"Breadcrumb for {deepest.path}: {' > '.join(crumbs) or '(none)'}")


def main() -> None:
    """Register the reader, read a clause file, and print what came back."""
    if len(sys.argv) > 2:
        print("Usage: python custom_reader.py [clause_file]")
        sys.exit(1)

    if len(sys.argv) == 2:
        try:
            source = Path(sys.argv[1]).read_text(encoding="utf-8")
        except OSError as error:
            print(f"Error: {error}")
            sys.exit(1)
    else:
        source = SAMPLE

    # 1. Claim a format name, and an extension for format detection.
    register_reader(ClauseFileReader(), replace=True)
    register_extension(".clf", "clause-file")

    print("A third-party reader for redlines")
    print("=" * 60)
    print(f"Registered formats: {', '.join(readers())}")
    print(f"Detection of 'deal.clf': {detect_format(path='deal.clf').format}")

    # 2. Look the reader up the way any caller would, by format name.
    reader = reader_for("clause-file")
    print(f"Reader for 'clause-file': {reader.name}")
    print(f"isinstance(reader, Reader): {isinstance(reader, Reader)}")
    print()

    # 3. Read, and the result is an ordinary block tree.
    describe(reader.read(source))


if __name__ == "__main__":
    main()
