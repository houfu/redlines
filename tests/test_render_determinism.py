r"""Determinism for every M3 output (N1, ADR-0037, #184).

N1 promises that identical inputs and configuration give identical output.
``str.__hash__`` is seeded once per interpreter start-up, so an iteration over
a ``set`` is consistent within a process and differs between processes, and
only a fresh interpreter under another ``PYTHONHASHSEED`` can see it
(``tests/helpers/hash_seed.py``, #135). Each renderer's own tests carry a check
of that kind for what it draws, and stay as they are. This module is the one
check over every output M3 adds, and holds them to two things.

**Hash seeds.** ``SCRIPT``, a ``python -c`` script, renders every output of the
sample pair's two twins, of each renderer case, of ``anchored`` and of
``notices``, and writes them as one JSON object. ``anchored`` has four
deletions and two move origins at one anchor, where the renderer cases have two
nodes at most: ordered by a hash, six nodes differ between seeds almost
always, two nodes half the time. ``notices`` has every header notice (a
filter, an exhausted budget, a dropped item on each side), which no other
subject has. `assert_byte_identical_across_hash_seeds` runs the script under
the five default seeds. What the seeds agreed on is then held to this
process's own render of the same comparisons, and to every committed golden of
an output, byte for byte. The golden files are accounted for, so one that
nothing compares fails the run, and `render_all` is held to every ``output_*``
method of `Comparison`, so a renderer that joins M3 later has to join this
check.

**A round trip** (F9, ADR-0038). A second render of one comparison, and a
render of ``Comparison.from_dict(comparison.to_dict(include_alignment=True))``,
are byte-equal to the first, for every output: the renderers read nothing that
is not on the wire. It runs over the same comparisons and the 60 committed
runs (``tests/helpers/committed_runs.py``).

Two details of the script are deliberate. It writes ASCII-only JSON through
``sys.stdout.buffer``, because the helper decodes the child's stdout with the
parent's locale encoding and universal newlines: on a CI locale that is not
UTF-8 the hostile case would be corrupted, and a ``\r`` in a document would be
read as a newline. And the script is not retyped here. It is assembled from the
source of the functions the tests below call in this process, so the two cannot
drift apart, and it imports nothing from ``tests``.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import subprocess
from pathlib import Path
from typing import Final, Literal

import pytest
from rich.text import Text

from redlines.alignment import AlignmentConfig
from redlines.comparison import Comparison, compare
from redlines.renderers._view import BlockStatus, build_view
from tests.helpers.committed_runs import (
    COMMITTED_RUN_COUNT,
    CommittedRun,
    committed_runs,
)
from tests.helpers.hash_seed import (
    DEFAULT_HASH_SEEDS,
    assert_byte_identical_across_hash_seeds,
    run_script_under_hash_seed,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE = REPO_ROOT / "tests" / "corpus" / "sample_pair"
EXPECTED = SAMPLE / "expected"
RENDERED = EXPECTED / "rendered"
CASES = REPO_ROOT / "tests" / "renderer_cases"

STYLES: Final[tuple[str, ...]] = (
    "red_green",
    "none",
    "red",
    "ghfm",
    "bbcode",
    "streamlit",
    "custom_css",
)
SYNTAXES: Final[tuple[Literal["text", "markdown", "html"], ...]] = (
    "text",
    "markdown",
    "html",
)
TWINS: Final[tuple[tuple[str, str, str], ...]] = (
    ("markdown", "md", "markdown"),
    ("text", "txt", "contract"),
)
"""The sample pair's twins: the format, the file extension and the profile its goldens were made under."""
NOTICES_SOURCE: Final = "Intro.\n\n***\n\nThe first clause stays.\n"
NOTICES_TEST: Final = "Intro.\n\n***\n\nThe first clause stays, edited.\n"
"""A pair whose thematic break each reader drops, so both sides report a dropped item."""
ANCHORED_SOURCE: Final = (
    "\n\n".join(
        (
            "# Terms",
            "The opening paragraph stays exactly where it is.",
            "The Supplier shall deliver the Goods to the Customer's premises on the Delivery Date.",
            "The Customer shall pay each invoice within thirty days of the date it is received.",
            "Either party may terminate this Agreement on ninety days' written notice to the other.",
            "Each party shall keep the other party's Confidential Information secret during the Term.",
            "The Supplier shall maintain adequate insurance cover throughout the Term of this Agreement.",
            "The Customer shall give the Supplier reasonable access to its premises and its staff.",
            "The closing paragraph stays exactly where it is.",
            "The governing law of this Agreement is the law of Singapore and its courts have jurisdiction.",
            "Notices under this Agreement shall be given in writing and delivered to the address stated above.",
        )
    )
    + "\n"
)
ANCHORED_TEST: Final = (
    "\n\n".join(
        (
            "# Terms",
            "The opening paragraph stays exactly where it is.",
            "The closing paragraph stays exactly where it is.",
            "The governing law of this Agreement is the law of Singapore and its courts have jurisdiction.",
            "Notices under this Agreement shall be given in writing and delivered to the address stated above.",
            "Each party shall keep the other party's Confidential Information secret during the Term.",
            "The Supplier shall deliver the Goods to the Customer's premises on the Delivery Date.",
        )
    )
    + "\n"
)
"""A pair in which four clauses are deleted and two move away from between the
opening and the closing paragraph: six nodes at one anchor, in source order."""


# -- what is rendered, and the script that renders it in a fresh interpreter -------------
#
# The three functions below are copied, as source, into SCRIPT, so they use
# nothing from this module but the constants above and `json`, `dataclasses`,
# `Path`, `compare` and `AlignmentConfig`.


def rich_record(text: Text) -> str:
    """``Text.plain`` and its spans as JSON: the goldens' form, which does not churn with rich."""
    spans = [[span.start, span.end, str(span.style)] for span in text.spans]
    return json.dumps({"plain": text.plain, "spans": spans}, ensure_ascii=False)


def render_all(comparison: Comparison) -> dict[str, str]:
    """Every output of one comparison, by name and in a fixed order."""
    outputs: dict[str, str] = {}
    for style in STYLES:
        outputs[f"output_markdown/{style}"] = comparison.output_markdown(style)
    outputs["output_markdown/custom_css/classes"] = comparison.output_markdown(
        "custom_css", ins_class="added", del_class="removed"
    )
    for syntax in SYNTAXES:
        for roles in (True, False):
            name = f"output_annotated/{syntax}/{'roles' if roles else 'no_roles'}"
            outputs[name] = comparison.output_annotated(syntax=syntax, roles=roles)
    outputs["output_html"] = comparison.output_html()
    outputs["output_rich"] = rich_record(comparison.output_rich())
    outputs["to_json"] = comparison.to_json(include_alignment=True)
    return outputs


def subjects(root: Path) -> dict[str, Comparison]:
    """The comparisons every check renders, by name.

    The sample pair's twins, read as its change-tree goldens read them; each
    renderer case, read as its goldens do; ``anchored``; and ``notices``. Every one pins the
    ``difflib`` backend, as the goldens do, so one golden holds on every
    Python and every set of extras.

    :param root: the repository's root.
    :return: the comparisons, twins first, then the cases by name, then ``anchored`` and ``notices``.
    """
    alignment = AlignmentConfig(similarity="difflib")
    found: dict[str, Comparison] = {}
    sample = root / "tests" / "corpus" / "sample_pair"
    for twin, extension, profile in TWINS:
        found[f"sample_pair/{twin}"] = compare(
            (sample / f"source.{extension}").read_text(encoding="utf-8"),
            (sample / f"test.{extension}").read_text(encoding="utf-8"),
            format=twin,
            profile=profile,
            alignment=alignment,
        )
    for directory in sorted((root / "tests" / "renderer_cases").iterdir()):
        if not (directory / "source.md").is_file():
            continue
        with open(directory / "source.md", encoding="utf-8", newline="") as handle:
            source = handle.read()
        with open(directory / "test.md", encoding="utf-8", newline="") as handle:
            test = handle.read()
        found[f"case/{directory.name}"] = compare(
            source, test, format="markdown", alignment=alignment
        )
    found["anchored"] = compare(
        ANCHORED_SOURCE, ANCHORED_TEST, format="markdown", alignment=alignment
    )
    dropping = compare(
        NOTICES_SOURCE, NOTICES_TEST, format="markdown", alignment=alignment
    )
    narrowed = dropping.filter(kinds=("modify", "insert"), min_chars=1, has_inline=True)
    found["notices"] = dataclasses.replace(
        narrowed, config=dataclasses.replace(narrowed.config, budget_exhausted=True)
    )
    return found


_SCRIPT_HEAD: Final = """\
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

from redlines.alignment import AlignmentConfig
from redlines.comparison import compare

"""
_SCRIPT_CONSTANTS: Final[dict[str, object]] = {
    "STYLES": STYLES,
    "SYNTAXES": SYNTAXES,
    "TWINS": TWINS,
    "NOTICES_SOURCE": NOTICES_SOURCE,
    "NOTICES_TEST": NOTICES_TEST,
    "ANCHORED_SOURCE": ANCHORED_SOURCE,
    "ANCHORED_TEST": ANCHORED_TEST,
}
_SCRIPT_TAIL: Final = r"""
outputs = {}
for subject, comparison in subjects(Path(".")).items():
    for name, text in render_all(comparison).items():
        outputs[subject + "/" + name] = text
sys.stdout.buffer.write(json.dumps(outputs, indent=0).encode("utf-8") + b"\n")
"""
SCRIPT: Final = (
    _SCRIPT_HEAD
    + "".join(f"{name} = {value!r}\n" for name, value in _SCRIPT_CONSTANTS.items())
    + "\n\n"
    + "\n\n".join(
        inspect.getsource(function) for function in (rich_record, render_all, subjects)
    )
    + _SCRIPT_TAIL
)
"""The script run under every hash seed. It writes the outputs as one ASCII JSON
object whose keys are ``SUBJECT/OUTPUT``, in a fixed order, and runs from the
repository's root."""


# -- the goldens -------------------------------------------------------------------------

Kind = Literal["text", "json"]
"""How a golden is compared: its bytes, or its JSON once parsed."""

CASE_NAMES: Final = tuple(
    directory.name
    for directory in sorted(CASES.iterdir())
    if (directory / "source.md").is_file()
)
SUBJECT_NAMES: Final = (
    *(f"sample_pair/{twin}" for twin, _, _ in TWINS),
    *(f"case/{name}" for name in CASE_NAMES),
    "anchored",
    "notices",
)
INPUTS: Final = ("source.md", "test.md")


def read(path: Path) -> str:
    """A file's text exactly as committed: no newline translation."""
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def committed_goldens() -> dict[str, tuple[Path, Kind]]:
    """Every golden of an output, by the key the script writes it under.

    :return: for each key ``SUBJECT/OUTPUT``, the file that holds its golden and
        how to compare it. The sample pair's goldens use the default syntax of
        their twin and roles on, as the renderers' own tests do; ``notices`` has none.
    """
    goldens: dict[str, tuple[Path, Kind]] = {}
    for twin, extension, profile in TWINS:
        subject = f"sample_pair/{twin}"
        for style in STYLES:
            goldens[f"{subject}/output_markdown/{style}"] = (
                RENDERED / f"markdown.{style}.{extension}",
                "text",
            )
        annotated = (
            "annotated.markdown.md" if twin == "markdown" else "annotated.contract.txt"
        )
        goldens[f"{subject}/output_annotated/{twin}/roles"] = (
            RENDERED / annotated,
            "text",
        )
        goldens[f"{subject}/output_annotated/html/roles"] = (
            RENDERED / f"annotated.{profile}.html",
            "text",
        )
        goldens[f"{subject}/output_html"] = (
            RENDERED / f"changes.{profile}.html",
            "text",
        )
        if twin == "markdown":
            goldens[f"{subject}/output_rich"] = (
                RENDERED / "rich.markdown.json",
                "json",
            )
        goldens[f"{subject}/to_json"] = (
            EXPECTED / f"change_tree.{profile}.json",
            "json",
        )
    for name in CASE_NAMES:
        subject, directory = f"case/{name}", CASES / name
        goldens[f"{subject}/output_markdown/none"] = (
            directory / "markdown.none.md",
            "text",
        )
        goldens[f"{subject}/output_annotated/markdown/roles"] = (
            directory / "annotated.markdown.md",
            "text",
        )
        goldens[f"{subject}/output_annotated/text/roles"] = (
            directory / "annotated.text.txt",
            "text",
        )
        goldens[f"{subject}/output_annotated/html/roles"] = (
            directory / "annotated.html",
            "text",
        )
        goldens[f"{subject}/output_html"] = (directory / "changes.html", "text")
    four_kinds = CASES / "four_kinds"
    for style in STYLES:
        if style != "none":
            goldens[f"case/four_kinds/output_markdown/{style}"] = (
                four_kinds / f"markdown.{style}.md",
                "text",
            )
    goldens["case/four_kinds/output_rich"] = (four_kinds / "rich.json", "json")
    return goldens


GOLDENS: Final = committed_goldens()


def golden_files_on_disk() -> list[Path]:
    """Every file that holds the golden of an output, wherever the repository keeps one."""
    files = [*RENDERED.iterdir(), *EXPECTED.glob("change_tree.*.json")]
    for name in CASE_NAMES:
        files.extend(
            path for path in (CASES / name).iterdir() if path.name not in INPUTS
        )
    return sorted(path for path in files if not path.name.startswith("."))


# -- the five seeds ----------------------------------------------------------------------


@dataclasses.dataclass
class Seeded:
    """What one run of `SCRIPT` under every default seed came to.

    :param raw: the bytes all the seeds wrote, or ``None`` if they disagreed
        or the script failed.
    :param crash: the script's failure, if it failed.
    """

    raw: str | None = None
    crash: subprocess.CalledProcessError | None = None

    @property
    def written(self) -> str:
        """The bytes the seeds wrote; skips the test if they did not agree."""
        if self.raw is None:
            pytest.skip(
                "no output the seeds agree on: see test_the_five_seeds_write_the_same_bytes"
            )
        return self.raw

    @property
    def outputs(self) -> dict[str, str]:
        """The outputs by ``SUBJECT/OUTPUT``; skips the test if the seeds did not agree."""
        outputs: dict[str, str] = json.loads(self.written)
        return outputs


@pytest.fixture(scope="module")
def seeded() -> Seeded:
    """One run of `SCRIPT` under every default seed, shared by the tests that read it."""
    try:
        raw = assert_byte_identical_across_hash_seeds(
            SCRIPT, seeds=DEFAULT_HASH_SEEDS, cwd=REPO_ROOT
        )
    except AssertionError:
        return Seeded()
    except subprocess.CalledProcessError as crash:
        return Seeded(crash=crash)
    return Seeded(raw=raw)


def disagreements() -> str:
    """Which outputs differ between the seeds, from running the script under each again."""
    runs: dict[str, dict[str, str]] = {
        seed: json.loads(run_script_under_hash_seed(SCRIPT, seed=seed, cwd=REPO_ROOT))
        for seed in DEFAULT_HASH_SEEDS
    }
    first_seed, first = next(iter(runs.items()))
    lines = []
    for seed, outputs in runs.items():
        differing = [
            key for key in {**first, **outputs} if first.get(key) != outputs.get(key)
        ]
        if differing:
            lines.append(
                f"PYTHONHASHSEED={seed!r} differs from PYTHONHASHSEED={first_seed!r} "
                f"on {len(differing)} outputs: {', '.join(differing)}"
            )
    return "\n".join(lines) or "the seeds agree when the script is run again"


def test_the_seed_matrix_has_at_least_five_distinct_seeds() -> None:
    assert len(set(DEFAULT_HASH_SEEDS)) >= 5


def test_the_seeds_tell_apart_an_iteration_over_a_set_of_strings() -> None:
    """The control: the failure this module looks for is one these seeds can see."""
    script = (
        "print(' '.join({'one', 'two', 'three', 'four', "
        "'five', 'six', 'seven', 'eight'}))"
    )
    printed = {
        run_script_under_hash_seed(script, seed=seed, cwd=REPO_ROOT)
        for seed in DEFAULT_HASH_SEEDS
    }
    assert len(printed) > 1


def test_the_anchored_comparison_puts_six_nodes_at_one_anchor() -> None:
    """Else its renders would not show what ordering them by a hash does."""
    longest = 0
    for node in build_view(subjects(REPO_ROOT)["anchored"]).walk():
        run = 0
        for child in node.children:
            standing = child.status in (BlockStatus.DELETE, BlockStatus.ORIGIN)
            run = run + 1 if standing else 0
            longest = max(longest, run)
    assert longest == 6


GHOSTS_BY_HASH: Final = """
import redlines.renderers._view as view
view.itemgetter = lambda index: lambda placed: hash(placed[1].block.path)
"""
"""Put before the script's last lines, it orders what shares an anchor by a hash
of its path instead of its rank in the source, which is what an unordered
iteration would amount to. `redlines.renderers._view` ranks them with
``sorted(..., key=itemgetter(0))``; if that changes, so must this."""


def test_the_five_seeds_would_see_nodes_at_one_anchor_ordered_by_a_hash() -> None:
    """The control for the whole script: it fails when the view's order is hash-seeded."""
    mutated = SCRIPT.replace(_SCRIPT_TAIL, GHOSTS_BY_HASH + _SCRIPT_TAIL)
    assert mutated != SCRIPT
    with pytest.raises(AssertionError):
        assert_byte_identical_across_hash_seeds(
            mutated, seeds=DEFAULT_HASH_SEEDS, cwd=REPO_ROOT
        )


def test_the_five_seeds_write_the_same_bytes(seeded: Seeded) -> None:
    if seeded.crash is not None:
        pytest.fail(
            f"the script exited {seeded.crash.returncode}:\n{seeded.crash.stderr}",
            pytrace=False,
        )
    if seeded.raw is None:
        pytest.fail(disagreements(), pytrace=False)
    assert all(output for output in seeded.outputs.values())


def test_the_script_writes_ascii_whatever_the_documents_hold(seeded: Seeded) -> None:
    assert seeded.written.isascii()
    assert any(not text.isascii() for text in seeded.outputs.values())


def test_the_script_does_not_depend_on_the_encoding_of_its_stdout(
    seeded: Seeded, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTHONIOENCODING", "ascii")
    printed = run_script_under_hash_seed(SCRIPT, seed="0", cwd=REPO_ROOT)
    assert json.loads(printed) == seeded.outputs


def test_the_seeds_write_what_this_process_renders(seeded: Seeded) -> None:
    here = {
        f"{subject}/{name}": text
        for subject, comparison in subjects(REPO_ROOT).items()
        for name, text in render_all(comparison).items()
    }
    assert list(seeded.outputs) == list(here)
    assert [key for key in here if seeded.outputs[key] != here[key]] == []


def test_the_notices_comparison_carries_every_header_notice(seeded: Seeded) -> None:
    """Else its renders would say nothing the other subjects do not.

    A filter, an exhausted budget and a dropped item on each side are four
    notes before the first block (ADR-0037).
    """
    blocks = seeded.outputs["notices/output_annotated/text/roles"].split("\n\n")
    assert [block.startswith("{>>") for block in blocks[:5]] == [True] * 4 + [False]


def test_render_all_covers_every_output_method_of_a_comparison() -> None:
    methods = {name for name in dir(Comparison) if name.startswith("output_")}
    drawn = {key.split("/")[0] for key in render_all(subjects(REPO_ROOT)["notices"])}
    assert methods <= drawn, sorted(methods - drawn)


# -- the goldens -------------------------------------------------------------------------


def test_every_golden_of_an_output_is_one_the_seeds_are_held_to() -> None:
    claimed = sorted(path for path, _ in GOLDENS.values())
    assert len(claimed) == len(set(claimed))
    assert claimed == golden_files_on_disk()


@pytest.mark.parametrize(
    "key",
    list(GOLDENS),
    ids=[str(path.relative_to(REPO_ROOT)) for path, _ in GOLDENS.values()],
)
def test_what_the_seeds_wrote_is_the_committed_golden(key: str, seeded: Seeded) -> None:
    path, kind = GOLDENS[key]
    golden = read(path)
    if kind == "json":
        assert json.loads(seeded.outputs[key]) == json.loads(golden)
    else:
        assert seeded.outputs[key] == golden


# -- the round trip (F9) -----------------------------------------------------------------


def assert_round_trips(comparison: Comparison, name: str) -> None:
    """F9 for every output: two renders agree, and so does one after ``from_dict(to_dict())``."""
    first = render_all(comparison)
    again = render_all(comparison)
    rebuilt = render_all(
        Comparison.from_dict(comparison.to_dict(include_alignment=True))
    )
    for what, other in (
        ("a second render", again),
        ("a render after the round trip", rebuilt),
    ):
        assert list(other) == list(first), name
        differing = [output for output in first if other[output] != first[output]]
        assert not differing, f"{name}: {what} differs on {differing}"


@pytest.mark.parametrize("name", SUBJECT_NAMES)
def test_a_comparison_renders_the_same_bytes_again_and_after_a_round_trip(
    name: str,
) -> None:
    assert_round_trips(subjects(REPO_ROOT)[name], name)


def test_the_comparisons_this_module_renders_are_the_ones_it_names() -> None:
    assert list(subjects(REPO_ROOT)) == list(SUBJECT_NAMES)
    assert len(CASE_NAMES) >= 5


RUNS = committed_runs()


def test_there_are_sixty_committed_runs() -> None:
    assert len(RUNS) == COMMITTED_RUN_COUNT


@pytest.mark.parametrize("run", RUNS, ids=[run.name for run in RUNS])
def test_a_committed_run_renders_the_same_bytes_again_and_after_a_round_trip(
    run: CommittedRun,
) -> None:
    source, test = run.texts()
    assert_round_trips(compare(source, test, format=run.format), run.name)
