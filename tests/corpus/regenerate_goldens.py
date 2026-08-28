"""Regenerate the golden files for the regression corpus.

Run this only when an output change is intentional, then review the diff:

    uv run python tests/corpus/regenerate_goldens.py

For every case directory under ``tests/corpus/``, the script reads
``source.txt`` and ``test.txt`` and writes ``golden/<style>.md`` for each
markdown style. The goldens are exact bytes: files are read and written with
``newline=""`` so no newline translation ever occurs, and ``tests/corpus/**``
is marked ``-text`` in ``.gitattributes`` so git cannot translate them either.

These files are the M0 regression corpus (ROADMAP § M0, PRD section 12) and
are reused by M4 to prove that the tree-based renderer is byte-identical to
the flat engine.
"""

from pathlib import Path

from redlines import Redlines
from redlines.enums import MarkdownStyle

CORPUS_DIR = Path(__file__).parent


def regenerate() -> None:
    for case_dir in sorted(CORPUS_DIR.iterdir()):
        if not case_dir.is_dir():
            continue
        source = (case_dir / "source.txt").read_text(encoding="utf-8")
        test = (case_dir / "test.txt").read_text(encoding="utf-8")
        golden_dir = case_dir / "golden"
        golden_dir.mkdir(exist_ok=True)
        for style in MarkdownStyle:
            output = Redlines(source, test, markdown_style=style.value).output_markdown
            with open(
                golden_dir / f"{style.value}.md", "w", encoding="utf-8", newline=""
            ) as f:
                f.write(output)
            print(f"wrote {case_dir.name}/golden/{style.value}.md")


if __name__ == "__main__":
    regenerate()
