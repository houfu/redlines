"""Fetch neurotic_docx_bench and extract its text, for local mutation only. Dev-only (ADR-0034).

`neurotic_docx_bench <https://github.com/frankiedrake/neurotic_docx_bench>`_ holds 763 pairs of
Word documents built to break document comparison. Its base documents are a genuinely useful
*text source* for :mod:`benchmark.mutate` -- real, awkward, nothing like the tidy contracts in
``tests/corpus/`` -- and this script is how a maintainer gets at them.

**Read this before running it.**

- **Run it by hand, never in CI, and never as part of a test.** Nothing in the committed corpus
  or in any gate depends on it. It clones from the network and needs a library this project does
  not depend on::

      uv run --with python-docx python benchmark/fetch_neurotic.py

  python-docx is deliberately not in ``pyproject.toml`` in any form -- not a dependency, not an
  optional extra, not a dev group -- because a benchmark convenience must not grow the surface
  the wheel or the Pyodide job has to carry (ADR-0004, ADR-0019).
- **Everything it writes goes under ``benchmark/corpus/external/``, which is gitignored**, and
  `_within_external` refuses any other destination rather than trusting the caller. The upstream
  repository is AGPL-licensed: its documents and the text extracted from them are never committed,
  never redistributed and never part of a published corpus. Numbers computed from them are
  reported as *not reproducible from this repository* (ADR-0034).
- **Extraction fails on some documents and that is expected.** Issue #96 already found python-docx
  unable to open 18 of the 763. Every skip is logged with its reason and the run continues; a
  fetch that crashed on the first bad file would be useless.

What this script does *not* do is re-run redlines through the bench's own adapter for a
like-for-like comparison with the published 45.9 figure. That benchmark scores a tracked-changes
DOCX, ADR-0014 rules out writing OOXML, and the 45.9 came from a third-party adapter rather than
from this project. ADR-0034 says so; this docstring repeats it so nobody reads "we fetched the
bench" as "we can re-run the bench".
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

__all__ = [
    "REPOSITORY",
    "EXTERNAL_DIR",
    "CLONE_NAME",
    "FetchError",
    "external_root",
    "clone",
    "extract_document",
    "extract_all",
    "main",
]

REPOSITORY = "https://github.com/frankiedrake/neurotic_docx_bench.git"

#: The only directory this script may write to, relative to the repository root. Gitignored.
EXTERNAL_DIR = Path("benchmark") / "corpus" / "external"

CLONE_NAME = "neurotic_docx_bench"


class FetchError(RuntimeError):
    """The fetch could not proceed: a missing library, a failed clone, a forbidden destination."""


def _repository_root() -> Path:
    return Path(__file__).resolve().parent.parent


def external_root(root: Path | None = None) -> Path:
    """Return the gitignored directory this script is allowed to write into."""
    return (root or _repository_root()) / EXTERNAL_DIR


def _within_external(path: Path, root: Path | None = None) -> Path:
    """Return `path` resolved, or raise if it is not inside ``benchmark/corpus/external/``.

    Checked rather than assumed: this script's whole licence story is that nothing it produces
    leaves the gitignored directory, and a story that depends on every caller passing the right
    argument is not a story.
    """
    allowed = external_root(root).resolve()
    resolved = path.resolve()
    if resolved != allowed and allowed not in resolved.parents:
        raise FetchError(
            f"refusing to write to {resolved}: benchmark/fetch_neurotic.py only ever writes "
            f"inside {allowed}, which is gitignored"
        )
    return resolved


def clone(root: Path | None = None, *, repository: str = REPOSITORY) -> Path:
    """Shallow-clone the bench into ``external/``, or update it if it is already there."""
    destination = _within_external(external_root(root) / CLONE_NAME, root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if (destination / ".git").is_dir():
        print(f"already cloned: {destination}")
        return destination
    print(f"cloning {repository} into {destination}")
    result = subprocess.run(
        ["git", "clone", "--depth", "1", repository, str(destination)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise FetchError(f"git clone failed: {result.stderr.strip()}")
    return destination


def _paragraphs(path: Path) -> list[str]:
    """Return the non-empty paragraph texts of a .docx, using python-docx.

    The import is local so that this module can be imported (and type-checked, and read) without
    python-docx installed; the error names the exact command that supplies it.
    """
    try:
        import docx
    except ImportError as exc:  # pragma: no cover - depends on the caller's environment
        raise FetchError(
            "python-docx is not installed, and this project deliberately does not depend on it. "
            "Run: uv run --with python-docx python benchmark/fetch_neurotic.py"
        ) from exc
    document = docx.Document(str(path))
    return [
        paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()
    ]


def extract_document(source: Path, destination: Path, root: Path | None = None) -> bool:
    """Extract one .docx to plain text. Returns whether it worked; a failure is logged, not raised.

    Text only: no styles, no tracked changes, no images. What the mutation operators want from
    these documents is awkward *prose*, and the less of the original file that comes across, the
    less there is to argue about.
    """
    _within_external(destination, root)
    try:
        paragraphs = _paragraphs(source)
    except FetchError:
        raise
    except Exception as exc:
        print(f"  skipped {source.name}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return False
    if not paragraphs:
        print(f"  skipped {source.name}: no paragraph text", file=sys.stderr)
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n\n".join(paragraphs) + "\n", encoding="utf-8", newline="\n")
    return True


def _documents(clone_dir: Path, *, name: str) -> Iterator[Path]:
    """Every ``<name>.docx`` in the clone, in sorted order so a run is reproducible."""
    yield from sorted(clone_dir.rglob(f"{name}.docx"))


def extract_all(
    clone_dir: Path, *, name: str = "base", root: Path | None = None
) -> tuple[int, int]:
    """Extract every matching document in `clone_dir` into ``external/text/``.

    :return: ``(extracted, skipped)``. Skips are expected -- #96 found 18 of the 763 unreadable --
        and are logged with their reason rather than ending the run.
    """
    text_dir = _within_external(external_root(root) / "text", root)
    extracted = skipped = 0
    for document in _documents(clone_dir, name=name):
        relative = document.relative_to(clone_dir).with_suffix(".txt")
        target = text_dir / str(relative).replace("/", "__")
        if extract_document(document, target, root):
            extracted += 1
        else:
            skipped += 1
    return extracted, skipped


def main(argv: list[str] | None = None) -> int:
    """Clone the bench and extract its text into ``benchmark/corpus/external/``."""
    parser = argparse.ArgumentParser(description="Fetch neurotic_docx_bench text (dev-only).")
    parser.add_argument("--repository", default=REPOSITORY, help="the git URL to clone")
    parser.add_argument(
        "--name", default="base", help="the document file name to extract (default: base)"
    )
    parser.add_argument(
        "--skip-clone", action="store_true", help="use an existing clone rather than fetching"
    )
    arguments = parser.parse_args(argv)

    try:
        clone_dir = (
            external_root() / CLONE_NAME
            if arguments.skip_clone
            else clone(repository=arguments.repository)
        )
        if not clone_dir.is_dir():
            raise FetchError(f"no clone at {clone_dir}; run without --skip-clone")
        extracted, skipped = extract_all(clone_dir, name=arguments.name)
    except FetchError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(
        f"extracted {extracted} document(s), skipped {skipped}, into {external_root() / 'text'}\n"
        "This text is AGPL-derived: it stays in benchmark/corpus/external/, which is gitignored, "
        "and is never committed or redistributed."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - a script entry point
    raise SystemExit(main())
