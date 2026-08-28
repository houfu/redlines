"""Regenerate the golden files for the regression corpus.

Run this only when an output change is intentional, then review the diff:

    uv run python tests/corpus/regenerate_goldens.py

For every case directory under ``tests/corpus/``, the script reads
``source.txt`` and ``test.txt`` and writes ``golden/<style>.md`` for each
markdown style. The goldens are exact bytes: files are read and written with
``newline=""`` so no newline translation ever occurs (matching how
``tests/test_corpus.py`` reads them), and ``tests/corpus/**`` is marked
``-text`` in ``.gitattributes`` so git cannot translate them either.

A case directory may contain an optional ``processor.txt`` naming a
non-default processor (currently only ``nupunkt``); the same file drives
``tests/test_corpus.py``, so the goldens are always generated with the
processor the test compares against.

These files are the M0 regression corpus (ROADMAP § M0, PRD section 12) and
are reused by M4 to prove that the tree-based renderer is byte-identical to
the flat engine.
"""

from pathlib import Path

from redlines import Redlines
from redlines.enums import MarkdownStyle
from redlines.processor import NupunktProcessor, RedlinesProcessor

CORPUS_DIR = Path(__file__).parent


def read_exact(path: Path) -> str:
    """Read a corpus file without any newline translation."""
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def processor_for(case_dir: Path) -> RedlinesProcessor | None:
    """Return the processor a case's optional ``processor.txt`` names."""
    marker = case_dir / "processor.txt"
    if not marker.is_file():
        return None
    name = read_exact(marker).strip()
    if name == "nupunkt":
        return NupunktProcessor()
    raise ValueError(f"Unknown processor {name!r} in {marker}")


def regenerate() -> None:
    for case_dir in sorted(CORPUS_DIR.iterdir()):
        if not case_dir.is_dir():
            continue
        source = read_exact(case_dir / "source.txt")
        test = read_exact(case_dir / "test.txt")
        processor = processor_for(case_dir)
        golden_dir = case_dir / "golden"
        golden_dir.mkdir(exist_ok=True)
        for style in MarkdownStyle:
            output = Redlines(
                source, test, processor=processor, markdown_style=style.value
            ).output_markdown
            with open(
                golden_dir / f"{style.value}.md", "w", encoding="utf-8", newline=""
            ) as f:
                f.write(output)
            print(f"wrote {case_dir.name}/golden/{style.value}.md")


if __name__ == "__main__":
    regenerate()
