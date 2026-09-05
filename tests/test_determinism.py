"""Cross-process determinism for alignment (#135, N1, ADR-0032).

`tests/test_alignment.py` and `tests/test_alignment_moves.py` already assert
that reading or aligning the same input twice, *in one process*, gives back
an equal record. That is not the promise N1 makes. `str.__hash__` is seeded
once per interpreter start-up, and a `dict` built by inserting the outputs of
a `set` iteration would come out consistently ordered within a process and
differently ordered between processes -- exactly the failure a same-process
test structurally cannot see, because it never starts a second process. This
module is the one that actually starts one, five times, under five different
seeds, and diffs the results byte for byte.

The reusable half of that -- run a script under several ``PYTHONHASHSEED``
values, assert identical stdout -- lives in
``tests/helpers/hash_seed.py`` rather than here, named so #137's JSON v2 test
can call the same function on ``Comparison.to_dict()`` once that exists,
without caring that this module happens to be testing `Alignment.to_dict()`.

The scripts below are self-contained ``python -c`` strings rather than
imports of a fixture module, because the whole point is that each seed starts
a *fresh* interpreter -- nothing here should share so much as an imported
module's already-computed state across the five runs.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.helpers.hash_seed import (
    DEFAULT_HASH_SEEDS,
    assert_byte_identical_across_hash_seeds,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DIR = Path(__file__).parent / "corpus" / "sample_pair" / "expected"

# A script that aligns the sample pair's markdown twin and prints
# `Alignment.to_dict()` as JSON, sorted only for readability of a failure
# message -- the equality check in the helper is on the raw stdout, unsorted,
# because *that* is what N1 promises: `to_dict()`'s own key order, not some
# canonical re-sorting of it.
_ALIGN_SAMPLE_PAIR = """
import json
from pathlib import Path
from redlines.alignment import align
from redlines.blocks import BlockTree

expected = Path({expected_dir!r})
source = BlockTree.from_dict(json.loads((expected / "source.markdown.json").read_text()))
test = BlockTree.from_dict(json.loads((expected / "test.markdown.json").read_text()))
print(json.dumps(align(source, test).to_dict()))
""".format(expected_dir=str(SAMPLE_DIR))

# A synthetic pair built to spend every pass at least once -- exact, label,
# structural, fuzzy, move and positional -- so a `dict`- or `set`-ordering bug
# hiding in any one of them has somewhere to show up. Twenty near-identical
# boilerplate clauses give the move pass's fuzzy stage a real field of
# leftovers to rank rather than a single obvious candidate; the two unlabelled
# paragraphs in section 2 give the *ordinary* fuzzy pass one too, scored and
# chosen among a genuine (if smaller) field rather than matched by label.
_ALIGN_SYNTHETIC_CASCADE = """
import json
from redlines.alignment import align
from redlines.blocks import Block, BlockKind, BlockTree

def block(kind, text="", *, label=None, children=()):
    return Block(kind=BlockKind(kind), text=text, label=label, children=children)

def section(label, *children):
    return block(
        "section",
        children=(block("heading", f"Section {label}", label=label), *children),
    )

def boiler(n):
    return block("paragraph", f"This is boilerplate clause number {n} of the schedule.")

INSURANCE = (
    "The Supplier shall maintain adequate insurance throughout the term "
    "of this agreement."
)
INSURANCE_EDITED = (
    "The Supplier shall maintain adequate insurance cover throughout the "
    "term of the agreement."
)
STATUS_REPORT = (
    "The Supplier shall deliver a written status report to the Customer "
    "every fortnight during the term."
)
STATUS_REPORT_EDITED = (
    "The Supplier shall deliver a written status report to the Customer "
    "every month during the term."
)
INVOICE_CLAUSE = (
    "The Customer shall pay all invoices within thirty days of the date "
    "of the invoice."
)
REVIEW_CLAUSE = (
    "The parties shall meet quarterly to review the performance of the "
    "agreement in good faith."
)

source = BlockTree.build(block(
    "document",
    children=(
        section(
            "1",
            block("list_item", "Alpha obligation text.", label="1.1"),
            block("list_item", "Beta obligation text.", label="1.2"),
            block(
                "list_item",
                "Each party shall return or destroy all Confidential "
                "Information on termination of this agreement.",
                label="1.3",
            ),
            block("list_item", INSURANCE, label="1.4"),
        ),
        section("2", *(boiler(n) for n in range(20))),
        section(
            "5",
            block("paragraph", "Introductory text for section five."),
            block("paragraph", STATUS_REPORT),
            block("paragraph", INVOICE_CLAUSE),
        ),
    ),
))
test = BlockTree.build(block(
    "document",
    children=(
        section(
            "1",
            block("list_item", "A brand new inserted clause.", label="1.1"),
            block("list_item", "Alpha obligation text, reworded a little.", label="1.2"),
            block("list_item", "Beta obligation text.", label="1.3"),
            block("list_item", INSURANCE_EDITED, label="1.4"),
        ),
        section(
            "3",
            block(
                "list_item",
                "Each party shall return or destroy all Confidential "
                "Information on termination of the agreement.",
            ),
            *(boiler(n) for n in range(20)),
        ),
        section(
            "5",
            block("paragraph", "Introductory text for section five."),
            block("paragraph", STATUS_REPORT_EDITED),
            block("paragraph", REVIEW_CLAUSE),
        ),
    ),
))
print(json.dumps(align(source, test).to_dict()))
"""


def test_aligning_the_sample_pair_is_byte_identical_across_hash_seeds() -> None:
    """The demo document, under the default configuration, five seeds."""
    output = assert_byte_identical_across_hash_seeds(
        _ALIGN_SAMPLE_PAIR, cwd=REPO_ROOT
    )
    result = json.loads(output)
    assert result["pass_counts"]["move"] == 1
    assert len(result["pairs"]) > 0


def test_aligning_a_synthetic_document_that_exercises_every_pass_is_deterministic() -> (
    None
):
    """A pair built so exact, label, structural, fuzzy, move and positional
    all fire at least once, still byte-identical across every seed.

    The moved clause is edited on its way across (a word changes), so the
    move pass finds it by its fuzzy stage rather than its exact one -- the
    stage that scores and ranks a whole field of boilerplate leftovers,
    precisely the shape a `dict` built from a `set` would reorder between
    processes. Two more clauses are edited in place, one keeping its label
    (caught by ``label``) and one losing its scope entirely by hiding among
    twenty near-identical siblings elsewhere (caught by the ordinary
    ``fuzzy`` pass, not the move pass's).
    """
    output = assert_byte_identical_across_hash_seeds(
        _ALIGN_SYNTHETIC_CASCADE, cwd=REPO_ROOT
    )
    result = json.loads(output)
    counts = result["pass_counts"]
    assert counts["exact"] > 0
    assert counts["label"] > 0
    assert counts["structural"] > 0
    assert counts["fuzzy"] > 0
    assert counts["move"] > 0
    assert counts["positional"] > 0


def test_the_default_hash_seeds_cover_at_least_three_distinct_seeds() -> None:
    """A sanity check on the matrix itself, not on alignment.

    If this list were ever accidentally collapsed to one seed, every test in
    this module would still pass -- against nothing. Pinning its size here is
    what would catch that.
    """
    assert len(DEFAULT_HASH_SEEDS) >= 3
    assert len(set(DEFAULT_HASH_SEEDS)) == len(DEFAULT_HASH_SEEDS)


# --- the configuration in force is on the wire (#135) -----------------------


def test_the_alignment_output_carries_the_configuration_in_force() -> None:
    """#135: a reader of the JSON must be able to see what produced it.

    ``config`` carries every `AlignmentConfig` field, including the
    similarity backend that was *asked* for, and ``backend`` carries the one
    that actually *ran* -- "auto resolved to difflib" and "difflib was
    demanded" are different facts, and both must survive serialisation.
    """
    output = assert_byte_identical_across_hash_seeds(
        _ALIGN_SAMPLE_PAIR, cwd=REPO_ROOT
    )
    result = json.loads(output)
    assert "config" in result
    assert "backend" in result
    assert result["backend"] in ("difflib", "rapidfuzz")
    config = result["config"]
    for key in (
        "passes",
        "similarity",
        "fuzzy_min_similarity",
        "label_min_similarity",
        "positional_min_similarity",
        "move_min_similarity",
        "move_tie_margin",
        "move_min_tokens",
        "move_kinds",
        "fuzzy_window",
        "table_fuzzy",
        "max_comparisons",
    ):
        assert key in config, f"the configuration on the wire is missing {key!r}"


def test_an_explicitly_requested_backend_is_recorded_as_both_asked_and_resolved() -> (
    None
):
    """Pinning ``similarity`` makes ``config.similarity`` and ``backend`` agree.

    Left on ``"auto"`` the two can differ (the sample-pair test above does
    not pin it); asking for ``"difflib"`` by name removes that freedom, and
    the record should say so plainly rather than only implicitly.
    """
    script = _ALIGN_SAMPLE_PAIR.replace(
        "print(json.dumps(align(source, test).to_dict()))",
        'from redlines.alignment import AlignmentConfig\n'
        'config = AlignmentConfig(similarity="difflib")\n'
        "print(json.dumps(align(source, test, config=config).to_dict()))",
    )
    output = assert_byte_identical_across_hash_seeds(script, cwd=REPO_ROOT)
    result = json.loads(output)
    assert result["backend"] == "difflib"
    assert result["config"]["similarity"] == "difflib"
