"""Executes the scripts in ``examples/``.

The examples are documentation: ADR-0027 has the 1.0 documentation pages
including their code from this directory rather than pasting it, which is only
worth doing if the code runs. These tests are what makes "the examples are
tested" a fact rather than a claim.

Each script is run the way its own README says to run it, in a subprocess, with
the interpreter running the test suite — so the examples are checked against the
installed package, not against an import path a test arranged for them.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

SOURCE_TEXT = "The quick brown fox jumps over the lazy dog."
CHANGED_TEXT = "The quick brown fox walks past the lazy dog."


def run_example(
    script: str, *args: str, cwd: Path | None = None, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run one example script and return the completed process."""
    return subprocess.run(
        [sys.executable, str(EXAMPLES / script), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
    )


@pytest.fixture
def file_pair(tmp_path: Path) -> tuple[Path, Path]:
    """One changed file pair."""
    old = tmp_path / "old.txt"
    new = tmp_path / "new.txt"
    old.write_text(SOURCE_TEXT, encoding="utf-8")
    new.write_text(CHANGED_TEXT, encoding="utf-8")
    return old, new


@pytest.fixture
def dir_pair(tmp_path: Path) -> tuple[Path, Path]:
    """Two directories holding a changed file, an unchanged file, a file
    missing from the second directory, and a file the default pattern skips."""
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()

    (old_dir / "changed.txt").write_text(SOURCE_TEXT, encoding="utf-8")
    (new_dir / "changed.txt").write_text(CHANGED_TEXT, encoding="utf-8")

    (old_dir / "unchanged.txt").write_text(SOURCE_TEXT, encoding="utf-8")
    (new_dir / "unchanged.txt").write_text(SOURCE_TEXT, encoding="utf-8")

    (old_dir / "only_in_old.txt").write_text(SOURCE_TEXT, encoding="utf-8")

    (old_dir / "notes.md").write_text(SOURCE_TEXT, encoding="utf-8")
    (new_dir / "notes.md").write_text(CHANGED_TEXT, encoding="utf-8")

    return old_dir, new_dir


class TestCompareFiles:
    """``compare_files.py old.txt new.txt``"""

    def test_reports_the_change(self, file_pair: tuple[Path, Path]) -> None:
        old, new = file_pair
        result = run_example("compare_files.py", str(old), str(new))

        assert result.returncode == 0, result.stderr
        assert "Total changes: 1" in result.stdout
        assert "Replacements: 1" in result.stdout
        # The diff itself, whatever markdown style is in force.
        assert "jumps over" in result.stdout
        assert "walks past" in result.stdout

    def test_identical_files_report_no_changes(self, tmp_path: Path) -> None:
        old = tmp_path / "old.txt"
        new = tmp_path / "new.txt"
        old.write_text(SOURCE_TEXT, encoding="utf-8")
        new.write_text(SOURCE_TEXT, encoding="utf-8")

        result = run_example("compare_files.py", str(old), str(new))

        assert result.returncode == 0, result.stderr
        assert "No changes detected" in result.stdout

    def test_missing_file_exits_one(self, tmp_path: Path, file_pair: tuple[Path, Path]) -> None:
        old, _ = file_pair
        result = run_example("compare_files.py", str(old), str(tmp_path / "absent.txt"))

        assert result.returncode == 1
        assert "Error:" in result.stdout

    def test_wrong_argument_count_prints_usage(self) -> None:
        result = run_example("compare_files.py")

        assert result.returncode == 1
        assert "Usage:" in result.stdout


class TestBatchDiff:
    """``batch_diff.py old/ new/ [pattern]``"""

    def test_summarises_a_directory_pair(self, dir_pair: tuple[Path, Path]) -> None:
        old_dir, new_dir = dir_pair
        result = run_example("batch_diff.py", str(old_dir), str(new_dir))

        assert result.returncode == 0, result.stderr
        assert "Total files: 3" in result.stdout
        assert "With changes: 1" in result.stdout
        assert "changed.txt" in result.stdout
        assert "Unchanged files: 1" in result.stdout
        assert "Missing in second directory:" in result.stdout
        assert "only_in_old.txt" in result.stdout
        # The default pattern is *.txt, so the markdown file is not compared.
        assert "notes.md" not in result.stdout

    def test_pattern_argument_selects_other_files(self, dir_pair: tuple[Path, Path]) -> None:
        old_dir, new_dir = dir_pair
        result = run_example("batch_diff.py", str(old_dir), str(new_dir), "*.md")

        assert result.returncode == 0, result.stderr
        assert "notes.md" in result.stdout
        assert "changed.txt" not in result.stdout

    def test_missing_directory_exits_one(self, tmp_path: Path, dir_pair: tuple[Path, Path]) -> None:
        old_dir, _ = dir_pair
        result = run_example("batch_diff.py", str(old_dir), str(tmp_path / "absent"))

        assert result.returncode == 1
        assert "is not a directory" in result.stdout


class TestGenerateReport:
    """``generate_report.py old/ new/ report.html [pattern]``"""

    def test_writes_a_report(self, tmp_path: Path, dir_pair: tuple[Path, Path]) -> None:
        old_dir, new_dir = dir_pair
        report = tmp_path / "report.html"

        result = run_example("generate_report.py", str(old_dir), str(new_dir), str(report))

        assert result.returncode == 0, result.stderr
        assert report.exists()

        html = report.read_text(encoding="utf-8")
        assert html.startswith("<!DOCTYPE html>")
        assert "changed.txt" in html
        # The template has to have been filled in, not emitted with its
        # placeholders intact.
        assert "{total_changes}" not in html
        assert "{file_sections}" not in html

    def test_missing_arguments_print_usage(self, tmp_path: Path) -> None:
        result = run_example("generate_report.py", str(tmp_path))

        assert result.returncode == 1
        assert "Usage:" in result.stdout


def git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run git in a throwaway repository, with an identity of its own so the
    test does not depend on the machine's git configuration."""
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "redlines tests",
        "GIT_AUTHOR_EMAIL": "tests@example.invalid",
        "GIT_COMMITTER_NAME": "redlines tests",
        "GIT_COMMITTER_EMAIL": "tests@example.invalid",
    }
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True
    )


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A repository with a documentation change on a branch off ``main``."""
    repo = tmp_path / "repo"
    repo.mkdir()

    git("-c", "init.defaultBranch=main", "init", cwd=repo)
    (repo / "guide.md").write_text(SOURCE_TEXT, encoding="utf-8")
    (repo / "unrelated.py").write_text("print('hello')\n", encoding="utf-8")
    git("add", ".", cwd=repo)
    git("commit", "-m", "initial", cwd=repo)

    git("checkout", "-b", "feature", cwd=repo)
    (repo / "guide.md").write_text(CHANGED_TEXT, encoding="utf-8")
    (repo / "new_page.md").write_text("A page that did not exist before.\n", encoding="utf-8")
    git("add", ".", cwd=repo)
    git("commit", "-m", "edit the guide", cwd=repo)

    return repo


class TestCiCheck:
    """``ci_check.py <base_branch> [pattern]``, run inside a git repository."""

    def test_reports_changes_against_the_base_branch(self, git_repo: Path) -> None:
        result = run_example("ci_check.py", "main", "*.md", cwd=git_repo)

        assert result.returncode == 0, result.stderr
        assert "DOCUMENTATION CHANGE REPORT" in result.stdout
        assert "guide.md" in result.stdout
        assert "new_page.md" in result.stdout
        # The pattern filters out the python file that also changed.
        assert "unrelated.py" not in result.stdout

    def test_writes_a_github_actions_summary(self, git_repo: Path, tmp_path: Path) -> None:
        summary = tmp_path / "step_summary.md"
        env = {**os.environ, "GITHUB_STEP_SUMMARY": str(summary)}

        result = run_example("ci_check.py", "main", "*.md", cwd=git_repo, env=env)

        assert result.returncode == 0, result.stderr
        written = summary.read_text(encoding="utf-8")
        assert "## 📄 Documentation Changes" in written
        assert "| `guide.md` |" in written

    def test_no_matching_changes_exits_zero(self, git_repo: Path) -> None:
        result = run_example("ci_check.py", "main", "*.rst", cwd=git_repo)

        assert result.returncode == 0, result.stderr
        assert "No files changed matching pattern" in result.stdout

    def test_missing_argument_prints_usage(self, git_repo: Path) -> None:
        result = run_example("ci_check.py", cwd=git_repo)

        assert result.returncode == 1
        assert "Usage:" in result.stdout


HOOK = EXAMPLES / "pre_commit_hook.sh"


class TestPreCommitHook:
    """``pre_commit_hook.sh``, installed as a git hook.

    The hook shells out to the ``redlines`` console script and parses its
    ``stats`` output, so running it is worth more than a syntax check: it is
    the only test that would notice the stats labels being renamed.
    """

    def test_parses_as_bash(self) -> None:
        bash = shutil.which("bash")
        if bash is None:
            pytest.skip("bash is not available")

        result = subprocess.run([bash, "-n", str(HOOK)], capture_output=True, text=True)

        assert result.returncode == 0, result.stderr

    @pytest.mark.skipif(sys.platform == "win32", reason="the hook is a bash script")
    def test_reports_staged_changes(self, git_repo: Path) -> None:
        bash = shutil.which("bash")
        if bash is None:
            pytest.skip("bash is not available")

        # The console script sits beside the interpreter running the tests.
        scripts_dir = Path(sys.executable).parent
        env = {**os.environ, "PATH": f"{scripts_dir}{os.pathsep}{os.environ['PATH']}"}
        if shutil.which("redlines", path=env["PATH"]) is None:
            pytest.skip("the redlines console script is not on PATH")

        (git_repo / "guide.md").write_text(
            "The quick brown fox strolls past the lazy dog.", encoding="utf-8"
        )
        git("add", "guide.md", cwd=git_repo)

        result = subprocess.run(
            [bash, str(HOOK)], cwd=git_repo, env=env, capture_output=True, text=True
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert "guide.md" in result.stdout
        assert "Files with changes: 1" in result.stdout
        assert "Pre-commit checks passed" in result.stdout


def test_every_example_is_exercised() -> None:
    """A new example without a test would otherwise be documentation nobody
    runs, which is the state this file exists to end."""
    exercised = {
        "compare_files.py",
        "batch_diff.py",
        "generate_report.py",
        "ci_check.py",
        "pre_commit_hook.sh",
    }
    present = {
        path.name
        for path in EXAMPLES.iterdir()
        if path.is_file() and path.suffix in {".py", ".sh"}
    }

    assert present == exercised, "examples/ has changed; add or remove a test above"
