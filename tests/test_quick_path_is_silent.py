"""Nothing on the quick path may warn.

What a 0.6 user copies, runs or types has to stay silent in 1.0: the README's
examples, the course example, the scripts in ``examples/`` and every command of
the CLI (ADR-0003: existing users "upgrade without noticing"). M3 adds the means
to deprecate things but no warning: the first ones are scheduled for 1.1. Most of
the install base is the course audience, running notebooks, where a warning is
noise on the page they are copying from. So a warning here means that a
deprecation was wired in early, or that a call started warning by accident.

How it is judged. Every run happens under ``warnings.catch_warnings(record=True)``
with ``simplefilter("always")``, so nothing is hidden by a default filter, by the
"once per location" memory or by a ``filterwarnings`` setting. A recorded warning
is redlines' own, and fails the test, when

1. its ``filename`` is under the installed ``redlines`` package: it was raised in
   our code; or
2. its category is, or subclasses, a class defined in the ``redlines`` package.
   None exists yet. The rule reads the module of every class in the category's
   MRO, so it applies to the first one that is added without being told about
   it. It matters because a deprecation warning is normally raised with
   ``stacklevel`` aimed at the *caller*: its filename is the user's code, not
   ours, and rule 1 alone would let it through; or
3. its ``filename`` is code this module wrote or compiled: itself, or a README
   block it runs. That is the same ``stacklevel`` effect when the caller is the
   test.

Everything else belongs to somebody else. click, rich-click, rich and pytest warn
about themselves from time to time (click 8.5 deprecates ``click.__version__``,
so a library that reads it warns). That is theirs to fix, and a test that fails
on a dependency bump is a test that gets switched off, so they are ignored: they
are told apart by where they were raised and by their category. A third-party
warning that names a line in ``redlines/`` is still counted, because it is our
code that asked for it. None is recorded today.

What it cannot see. The README blocks, the course example and the CLI run in this
process, where ``redlines`` was imported long before; an import-time warning is
outside them. The scripts in ``examples/`` run in a fresh interpreter, so a warning
on ``import redlines`` shows up there. ``tests/test_examples.py`` is pinned and
checks the scripts' output, not their warnings, so they are run again here. A
warning of a built-in category that ``stacklevel`` aims at an example script is
not counted (the scripts are not code this module wrote, and rules 1 and 2 do not
match it); redlines' own warning classes, which rule 2 catches, are how the
library will warn.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import warnings
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import click
import pytest
from click.testing import CliRunner

import redlines
from redlines import Redlines
from redlines.cli import cli
from redlines.enums import MarkdownStyle
from redlines.processor import NUPUNKT_AVAILABLE

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"
EXAMPLES = REPO_ROOT / "examples"
COURSE_DIR = Path(__file__).resolve().parent / "corpus" / "course_lesson6"

REDLINES_DIR = Path(redlines.__file__).resolve().parent
THIS_FILE = Path(__file__).resolve()
README_BLOCK = "<README.md python block "

SOURCE_TEXT = "The quick brown fox jumps over the lazy dog."
CHANGED_TEXT = "The quick brown fox walks past the lazy dog."


# --- the rules -------------------------------------------------------------


@dataclass(frozen=True)
class Raised:
    """One recorded warning, reduced to what the rules look at.

    ``categories`` is the warning's category followed by its bases, each as
    ``module.qualname``. Reduced to strings, a warning recorded in this process
    and one reported by a child process are judged by the same code.
    """

    filename: str
    lineno: int
    categories: tuple[str, ...]
    message: str

    @classmethod
    def of(cls, warning: warnings.WarningMessage) -> Raised:
        return cls(
            filename=warning.filename,
            lineno=warning.lineno,
            categories=tuple(
                f"{base.__module__}.{base.__qualname__}"
                for base in warning.category.__mro__
            ),
            message=str(warning.message),
        )

    def __str__(self) -> str:
        category = self.categories[0].rsplit(".", 1)[-1]
        return f"{self.filename}:{self.lineno}: {category}: {self.message}"


def _is_under(filename: str, directory: Path) -> bool:
    if filename.startswith("<"):  # <string>, <stdin>, a README block
        return False
    try:
        return Path(filename).resolve().is_relative_to(directory)
    except (OSError, ValueError):
        return False


def _is_this_file(filename: str) -> bool:
    if filename.startswith("<"):
        return False
    try:
        return Path(filename).resolve() == THIS_FILE
    except (OSError, ValueError):
        return False


def _defined_in_redlines(qualified_name: str) -> bool:
    module = qualified_name.rpartition(".")[0]
    return module == "redlines" or module.startswith("redlines.")


def blame(raised: Raised) -> str | None:
    """Why a recorded warning counts as redlines' own, or None when it is
    somebody else's."""
    if _is_under(raised.filename, REDLINES_DIR):
        return "raised inside the redlines package"
    if any(_defined_in_redlines(name) for name in raised.categories):
        return "its category is defined in the redlines package"
    if raised.filename.startswith(README_BLOCK) or _is_this_file(raised.filename):
        return "attributed to the calling code by stacklevel"
    return None


def assert_silent(what: str, recorded: Iterable[Raised]) -> None:
    __tracebackhide__ = True
    ours = [(raised, why) for raised in recorded if (why := blame(raised)) is not None]
    if ours:
        report = "\n".join(f"  {raised}\n    -> {why}" for raised, why in ours)
        raise AssertionError(
            f"{what} must stay silent in 1.0, but raised {len(ours)} warning(s) "
            f"of redlines':\n{report}\n"
            f"Nothing a 0.6 user copies may warn before 1.1; see the docstring of "
            f"tests/test_quick_path_is_silent.py."
        )


@contextlib.contextmanager
def recording() -> Iterator[list[warnings.WarningMessage]]:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        yield caught


# --- the README blocks and the course example (in this process) ------------


def python_blocks(markdown: str) -> list[str]:
    """The bodies of the ``python`` fenced blocks of a markdown document.

    A copy of the function of the same name in ``tests/test_readme_strings.py``,
    which tests it; the two test modules do not import each other.
    """
    blocks: list[str] = []
    in_fence = False
    keep = False
    lines: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_fence:
                if keep:
                    blocks.append("\n".join(lines) + "\n")
                in_fence = False
            else:
                info = stripped[3:].split()
                in_fence = True
                keep = bool(info) and info[0] == "python"
                lines = []
        elif in_fence and keep:
            lines.append(line)
    if in_fence and keep:
        blocks.append("\n".join(lines) + "\n")
    return blocks


BLOCKS = python_blocks(README.read_text(encoding="utf-8"))


def run_readme_block(index: int, code: str) -> list[Raised]:
    """Run one README block in a namespace of its own; what it warned about."""
    compiled = compile(code, f"{README_BLOCK}{index + 1}>", "exec")
    with recording() as caught, contextlib.redirect_stdout(io.StringIO()):
        exec(compiled, {"__name__": "readme_block"})
    return [Raised.of(warning) for warning in caught]


def test_readme_has_python_blocks() -> None:
    assert BLOCKS, "README.md has no ```python fenced block to run"


@pytest.mark.parametrize(
    "index", range(len(BLOCKS)), ids=lambda index: f"block-{index + 1}"
)
def test_readme_python_block_is_silent(index: int) -> None:
    code = BLOCKS[index]
    if "nupunkt" in code.lower() and not NUPUNKT_AVAILABLE:
        pytest.skip("this README block needs the nupunkt extra, which is not installed")

    assert_silent(f"README.md python block {index + 1}", run_readme_block(index, code))


def read_exact(path: Path) -> str:
    """Read a file without any newline translation."""
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def test_course_example_is_silent() -> None:
    """Lesson 6 of the DeepLearning.AI course: ``Redlines(a, b).output_markdown``,
    called from here, so a warning aimed at the caller by ``stacklevel`` lands
    on this module."""
    source = read_exact(COURSE_DIR / "source.txt")
    test = read_exact(COURSE_DIR / "test.txt")

    with recording() as caught:
        markdown = Redlines(source, test).output_markdown

    assert markdown
    assert_silent("the course example", [Raised.of(warning) for warning in caught])


# --- the CLI (in this process) ---------------------------------------------

# Every way to run a command, as (the command it exercises, the arguments that
# come before the two inputs). `compare` is the default command, so it is run
# with and without its name. The function `simple_text` is the command
# `simple-text`. `guide --open` is not run: it opens a browser.
INVOCATIONS: list[tuple[str, tuple[str, ...]]] = [
    ("compare", ("compare",)),
    ("compare", ("compare", "--pretty")),
    ("compare", ()),
    ("compare", ("--pretty",)),
    ("text", ("text",)),
    ("text", ("text", "--quiet")),
    ("simple-text", ("simple-text",)),
    ("json", ("json",)),
    ("json", ("json", "--pretty")),
    ("stats", ("stats",)),
    ("stats", ("stats", "--quiet")),
    *(
        ("markdown", ("markdown", "--markdown-style", style.value))
        for style in MarkdownStyle
    ),
    *(
        ("markdown", ("markdown", "--quiet", "--markdown-style", style.value))
        for style in MarkdownStyle
    ),
]

# The inputs a command can be given: literal strings, and files (the course
# pair, which is longer and has six edits).
CLI_INPUTS = {
    "strings": (SOURCE_TEXT, CHANGED_TEXT),
    "files": (str(COURSE_DIR / "source.txt"), str(COURSE_DIR / "test.txt")),
}


@pytest.mark.parametrize("form", CLI_INPUTS)
@pytest.mark.parametrize(
    "arguments",
    [
        pytest.param(arguments, id="-".join(arguments) or "default")
        for _, arguments in INVOCATIONS
    ],
)
def test_cli_command_is_silent(arguments: tuple[str, ...], form: str) -> None:
    source, test = CLI_INPUTS[form]

    with recording() as caught:
        result = CliRunner().invoke(cli, [*arguments, source, test])

    # Exit code 0 is "changes found": the command ran to its end. 1 would mean
    # "no changes" and 2 an error, and a run that stopped early proves nothing.
    assert result.exit_code == 0, result.output
    assert_silent(
        f"`redlines {' '.join(arguments)}` on {form}",
        [Raised.of(warning) for warning in caught],
    )


def test_cli_guide_is_silent() -> None:
    with recording() as caught:
        result = CliRunner().invoke(cli, ["guide"])

    assert result.exit_code == 0, result.output
    assert_silent("`redlines guide`", [Raised.of(warning) for warning in caught])


def test_every_cli_command_is_exercised() -> None:
    """A command added without a run above would be a quick path nobody checks."""
    exercised = {command for command, _ in INVOCATIONS} | {"guide"}

    assert exercised == set(cli.commands), "the CLI has changed; update INVOCATIONS"


# --- the scripts in examples/ (a fresh interpreter each) -------------------

# The child process: it runs one script the way `python script.py args` would,
# records every warning from before the script's first import, and writes what it
# recorded to a JSON file for the parent to judge. A script of its own, and not
# `python -W always` with a parse of stderr, because a warning printed to stderr
# has lost the module of its category, which rule 2 needs. A fresh interpreter,
# and not an import into this one, so that a warning at import time is seen and
# so that `custom_reader.py` registering a reader leaks into no other test.
_CHILD = """
import json, os, runpy, sys, warnings

report, script, *arguments = sys.argv[1:]
sys.argv = [script, *arguments]
sys.path[0] = os.path.dirname(os.path.abspath(script))
status = 0
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    try:
        runpy.run_path(script, run_name="__main__")
    except SystemExit as stop:
        status = stop.code if isinstance(stop.code, int) else int(stop.code is not None)
recorded = [
    {
        "filename": w.filename,
        "lineno": w.lineno,
        "categories": [f"{c.__module__}.{c.__qualname__}" for c in w.category.__mro__],
        "message": str(w.message),
    }
    for w in caught
]
with open(report, "w", encoding="utf-8") as out:
    json.dump({"status": status, "warnings": recorded}, out)
"""


@dataclass(frozen=True)
class ScriptRun:
    status: int
    stdout: str
    raised: list[Raised]


def child_env(**extra: str) -> dict[str, str]:
    """The environment of a child: UTF-8 whatever the locale (the examples print
    symbols), and no GITHUB_STEP_SUMMARY unless a test sets one, so that a run
    inside GitHub Actions does not overwrite the job's own summary."""
    env = {k: v for k, v in os.environ.items() if k != "GITHUB_STEP_SUMMARY"}
    env["PYTHONUTF8"] = "1"
    env.update(extra)
    return env


def run_script(
    script: Path,
    *arguments: str,
    cwd: Path,
    report: Path,
    env: Mapping[str, str] | None = None,
) -> ScriptRun:
    completed = subprocess.run(
        [sys.executable, "-c", _CHILD, str(report), str(script), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=cwd,
        env=dict(env) if env is not None else child_env(),
    )
    assert (
        completed.returncode == 0
    ), f"{script.name} did not finish:\n{completed.stderr}"

    data = json.loads(report.read_text(encoding="utf-8"))
    return ScriptRun(
        status=data["status"],
        stdout=completed.stdout,
        raised=[
            Raised(
                filename=item["filename"],
                lineno=item["lineno"],
                categories=tuple(item["categories"]),
                message=item["message"],
            )
            for item in data["warnings"]
        ],
    )


def write_directories(root: Path) -> tuple[Path, Path]:
    """Two directories: a changed file, an unchanged one and one that exists
    only in the first."""
    old_dir, new_dir = root / "old", root / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    (old_dir / "changed.txt").write_text(SOURCE_TEXT, encoding="utf-8")
    (new_dir / "changed.txt").write_text(CHANGED_TEXT, encoding="utf-8")
    (old_dir / "unchanged.txt").write_text(SOURCE_TEXT, encoding="utf-8")
    (new_dir / "unchanged.txt").write_text(SOURCE_TEXT, encoding="utf-8")
    (old_dir / "only_in_old.txt").write_text(SOURCE_TEXT, encoding="utf-8")
    return old_dir, new_dir


def test_compare_files_example_is_silent(tmp_path: Path) -> None:
    old, new = tmp_path / "old.txt", tmp_path / "new.txt"
    old.write_text(SOURCE_TEXT, encoding="utf-8")
    new.write_text(CHANGED_TEXT, encoding="utf-8")

    run = run_script(
        EXAMPLES / "compare_files.py",
        str(old),
        str(new),
        cwd=tmp_path,
        report=tmp_path / "warnings.json",
    )

    assert run.status == 0
    assert "Total changes: 1" in run.stdout  # it reached the library calls
    assert_silent("examples/compare_files.py", run.raised)


def test_batch_diff_example_is_silent(tmp_path: Path) -> None:
    old_dir, new_dir = write_directories(tmp_path)

    run = run_script(
        EXAMPLES / "batch_diff.py",
        str(old_dir),
        str(new_dir),
        cwd=tmp_path,
        report=tmp_path / "warnings.json",
    )

    assert run.status == 0
    assert "With changes: 1" in run.stdout
    assert_silent("examples/batch_diff.py", run.raised)


def test_generate_report_example_is_silent(tmp_path: Path) -> None:
    old_dir, new_dir = write_directories(tmp_path)

    run = run_script(
        EXAMPLES / "generate_report.py",
        str(old_dir),
        str(new_dir),
        str(tmp_path / "report.html"),
        cwd=tmp_path,
        report=tmp_path / "warnings.json",
    )

    assert run.status == 0
    assert "Files with changes: 1" in run.stdout
    assert_silent("examples/generate_report.py", run.raised)


def git(*arguments: str, cwd: Path) -> None:
    identity = {
        "GIT_AUTHOR_NAME": "redlines tests",
        "GIT_AUTHOR_EMAIL": "tests@example.invalid",
        "GIT_COMMITTER_NAME": "redlines tests",
        "GIT_COMMITTER_EMAIL": "tests@example.invalid",
    }
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *arguments],
        cwd=cwd,
        env=child_env(**identity),
        capture_output=True,
        text=True,
        check=True,
    )


def test_ci_check_example_is_silent(tmp_path: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git is not available")

    # The way tests/test_examples.py sets it up: a documentation change on a
    # branch off main, in a repository of its own.
    repo = tmp_path / "repo"
    repo.mkdir()
    git("-c", "init.defaultBranch=main", "init", cwd=repo)
    (repo / "guide.md").write_text(SOURCE_TEXT, encoding="utf-8")
    git("add", ".", cwd=repo)
    git("commit", "-m", "initial", cwd=repo)
    git("checkout", "-b", "feature", cwd=repo)
    (repo / "guide.md").write_text(CHANGED_TEXT, encoding="utf-8")
    git("add", ".", cwd=repo)
    git("commit", "-m", "edit the guide", cwd=repo)

    run = run_script(
        EXAMPLES / "ci_check.py",
        "main",
        "*.md",
        cwd=repo,
        report=tmp_path / "warnings.json",
        env=child_env(GITHUB_STEP_SUMMARY=str(tmp_path / "summary.md")),
    )

    assert run.status == 0
    assert "Documentation changes detected" in run.stdout
    assert_silent("examples/ci_check.py", run.raised)


def test_custom_reader_example_is_silent(tmp_path: Path) -> None:
    """It does not touch the 0.6 surface, but it is an example, and it is what a
    third party copies to write a reader."""
    run = run_script(
        EXAMPLES / "custom_reader.py", cwd=tmp_path, report=tmp_path / "warnings.json"
    )

    assert run.status == 0
    assert "Fallback blocks: 1" in run.stdout
    assert_silent("examples/custom_reader.py", run.raised)


def test_every_example_script_is_run() -> None:
    """``pre_commit_hook.sh`` runs ``redlines stats --quiet``, which the CLI
    tests above run. A new Python example needs a test of its own here."""
    present = {path.name for path in EXAMPLES.glob("*.py")}

    assert present == {
        "batch_diff.py",
        "ci_check.py",
        "compare_files.py",
        "custom_reader.py",
        "generate_report.py",
    }, "examples/ has changed; run the new script in this module"


# --- the rules and the harness, tried on warnings made on purpose ----------
#
# Nothing in redlines warns yet, so without these the tests above could not tell
# a rule that works from one that never fires.


def library_that_warns_at_its_caller() -> None:
    warnings.warn("an old name", FutureWarning, stacklevel=2)


def recorded_by(emit: Callable[[], None]) -> list[Raised]:
    with recording() as caught:
        emit()
    return [Raised.of(warning) for warning in caught]


def test_a_warning_raised_inside_the_package_is_counted() -> None:
    with recording() as caught:
        warnings.warn_explicit(
            "m", UserWarning, filename=str(REDLINES_DIR / "redlines.py"), lineno=1
        )
    [raised] = [Raised.of(warning) for warning in caught]

    assert blame(raised) == "raised inside the redlines package"
    with pytest.raises(AssertionError, match="must stay silent"):
        assert_silent("a call", [raised])


def test_a_warning_class_of_the_package_is_counted_wherever_it_points() -> None:
    # No such class exists yet, so make one that claims to live in the package,
    # and one that subclasses it from elsewhere.
    in_package = cast(
        "type[Warning]",
        type("PackageWarning", (DeprecationWarning,), {"__module__": "redlines.x"}),
    )
    narrower = cast("type[Warning]", type("Narrower", (in_package,), {}))

    for category in (in_package, narrower):
        with recording() as caught:
            # Aimed at the user's own file, as stacklevel=3 would aim it.
            warnings.warn_explicit(
                "m", category, filename="/somewhere/user_code.py", lineno=7
            )
        [raised] = [Raised.of(warning) for warning in caught]

        assert blame(raised) == "its category is defined in the redlines package"


def test_a_warning_aimed_at_this_module_by_stacklevel_is_counted() -> None:
    [raised] = recorded_by(library_that_warns_at_its_caller)

    assert raised.filename == str(THIS_FILE)
    assert blame(raised) == "attributed to the calling code by stacklevel"


def test_a_warning_aimed_at_a_readme_block_is_counted() -> None:
    [raised] = run_readme_block(0, "import warnings\nwarnings.warn('boom')\n")

    assert raised.filename == "<README.md python block 1>"
    assert blame(raised) == "attributed to the calling code by stacklevel"


@pytest.mark.parametrize(
    "filename",
    [
        str(Path(click.__file__).parent / "core.py"),
        str(Path(pytest.__file__).parent / "__init__.py"),
        "/somewhere/else/entirely.py",
    ],
    ids=["click", "pytest", "elsewhere"],
)
def test_a_third_party_warning_is_not_counted(filename: str) -> None:
    with recording() as caught:
        warnings.warn_explicit("m", DeprecationWarning, filename=filename, lineno=1)
    [raised] = [Raised.of(warning) for warning in caught]

    assert blame(raised) is None
    assert_silent("a call that only third parties warned in", [raised])


def test_the_script_harness_sees_warnings_and_exit_codes(tmp_path: Path) -> None:
    script = tmp_path / "noisy.py"
    script.write_text(
        "import sys, warnings\n"
        "class FromRedlines(DeprecationWarning):\n"
        "    __module__ = 'redlines._deprecation'\n"
        "warnings.warn('a third party might say this', DeprecationWarning)\n"
        "warnings.warn('redlines would say this', FromRedlines)\n"
        "sys.exit(3)\n",
        encoding="utf-8",
    )

    run = run_script(script, cwd=tmp_path, report=tmp_path / "warnings.json")

    assert run.status == 3
    third_party, ours = run.raised
    assert third_party.filename == str(script)
    assert third_party.categories[0] == "builtins.DeprecationWarning"
    assert blame(third_party) is None
    assert ours.categories[0] == "redlines._deprecation.FromRedlines"
    assert blame(ours) == "its category is defined in the redlines package"
