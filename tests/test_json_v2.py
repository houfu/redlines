"""Real `jsonschema` validation of real output against the published schema (#137).

`redlines/schemas/comparison-v2.json` is the freeze: the wire shape
`Comparison.to_dict()`/`to_json()` produce, at `schema_version` ``"2.0"``.
Unlike the profile schema (hand-validated in ``tests/test_profiles.py``,
because ``jsonschema`` was not yet a dependency when that module was
written), this one is dev-only and available (ADR-0032's `pyproject.toml`
already lists it), so this module runs the real validator over the real
output of `compare()` -- the sample pair under both of its profiles, a
comparison with no changes at all, and a comparison written with
``include_alignment=True`` -- rather than asserting the schema's shape by
hand and hoping it matches.

Two things freeze here that are *not* transcriptions of the research
document's own JSON example, because that example was drafted before
#138 (filters) and #139 (statistics) existed and sketches fields those
modules will add later: this schema's top level is exactly
``schema_version, config, source, test, changes`` plus the optional
``alignment`` -- no ``statistics`` key, because `Comparison.to_dict()` does
not have one -- and ``config`` carries no ``filter`` key, because
`ComparisonConfig` does not have one either. Adding either later is an
additive, minor-version change (ADR-0011) that widens this same file; this
test module is what will need updating alongside it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from redlines.blocks import BlockTree
from redlines.comparison import SCHEMA_VERSION, comparison_schema_text, compare

SAMPLE_DIR = Path(__file__).parent / "corpus" / "sample_pair" / "expected"


def _sample_trees(fmt: str) -> tuple[BlockTree, BlockTree]:
    """Load the sample pair's already-parsed trees for one format twin."""
    source = BlockTree.from_dict(
        json.loads((SAMPLE_DIR / f"source.{fmt}.json").read_text(encoding="utf-8"))
    )
    test = BlockTree.from_dict(
        json.loads((SAMPLE_DIR / f"test.{fmt}.json").read_text(encoding="utf-8"))
    )
    return source, test


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    """The published schema, parsed once for the whole module."""
    parsed: dict[str, Any] = json.loads(comparison_schema_text())
    return parsed


@pytest.fixture(scope="module")
def validator(schema: dict[str, Any]) -> jsonschema.protocols.Validator:
    """A validator built once, reused by every test in this module."""
    jsonschema.Draft7Validator.check_schema(schema)
    return jsonschema.Draft7Validator(schema)


# --- the schema file itself --------------------------------------------------


def test_the_schema_is_a_valid_draft_07_schema(schema: dict[str, Any]) -> None:
    """Not just parseable JSON: an actual schema, under the draft it claims."""
    assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
    jsonschema.Draft7Validator.check_schema(schema)


def test_the_schema_id_is_the_site_url_it_will_be_published_at(
    schema: dict[str, Any],
) -> None:
    """M4's obligation, named where a reader of the schema will see it.

    ``site/public/schemas/`` does not exist yet (ROADMAP § M0 is wrong about
    this); M2 ships the in-package file with the ``$id`` M4 will publish it
    at, per the #137 PR body.
    """
    assert (
        schema["$id"] == "https://houfu.github.io/redlines/schemas/comparison-v2.json"
    )


def test_the_schema_version_const_matches_schema_version(
    schema: dict[str, Any],
) -> None:
    """Drift test: the file's own ``const`` and the constant in Python agree.

    The same discipline ADR-0028 applies to the profile schema against its
    loader -- a schema that quietly drifted from the constant it is supposed
    to freeze would be worse than no schema at all.
    """
    assert schema["properties"]["schema_version"]["const"] == SCHEMA_VERSION


def test_the_block_tree_is_a_section_of_this_file_not_a_second_schema(
    schema: dict[str, Any],
) -> None:
    """One ``$id``, one version, one freeze (#137) -- verified structurally."""
    assert "blockTree" in schema["definitions"]
    assert schema["properties"]["source"]["$ref"] == "#/definitions/blockTree"
    assert schema["properties"]["test"]["$ref"] == "#/definitions/blockTree"


def test_comparison_schema_text_matches_the_file_on_disk() -> None:
    """`comparison_schema_text` reads the installed package, not a copy."""
    on_disk = (
        Path(__file__).parent.parent / "redlines" / "schemas" / "comparison-v2.json"
    ).read_text(encoding="utf-8")
    assert comparison_schema_text() == on_disk


def test_the_schemas_package_is_wheel_packaged() -> None:
    """`redlines.schemas` is a real package, so `importlib.resources` finds it.

    A namespace package (no ``__init__.py``) resolves inconsistently across
    installers; this is the same discipline `redlines.profiles` already
    relies on for its own ``schema.json``.
    """
    import redlines.schemas

    assert redlines.schemas.__file__ is not None


# --- real output, against the real schema ------------------------------------


@pytest.mark.parametrize("fmt", ["contract", "markdown"])
def test_the_sample_pair_comparison_validates_under_both_profiles(
    validator: jsonschema.protocols.Validator, fmt: str
) -> None:
    """The PRD § 3a demo document, read under its own profile, validates."""

    source, test = _sample_trees(fmt)
    result = compare(source, test)
    validator.validate(result.to_dict())


def test_a_comparison_with_include_alignment_validates(
    validator: jsonschema.protocols.Validator,
) -> None:
    """The optional ``alignment`` key, present, still matches the schema."""

    source, test = _sample_trees("markdown")
    result = compare(source, test)
    payload = result.to_dict(include_alignment=True)
    assert "alignment" in payload
    validator.validate(payload)


def test_an_empty_comparison_validates(
    validator: jsonschema.protocols.Validator,
) -> None:
    """Comparing a document against itself: no changes, still a valid document."""

    source, _test = _sample_trees("contract")
    result = compare(source, source)
    payload = result.to_dict(include_alignment=True)
    assert payload["changes"] == []
    validator.validate(payload)


def test_to_json_round_trips_through_the_schema(
    validator: jsonschema.protocols.Validator,
) -> None:
    """`to_json()`'s own text, re-parsed, is what the schema was checked against."""

    source, test = _sample_trees("markdown")
    result = compare(source, test)
    reparsed = json.loads(result.to_json(include_alignment=True))
    validator.validate(reparsed)
    assert reparsed == result.to_dict(include_alignment=True)


def test_a_comparison_missing_a_required_top_level_key_fails_validation(
    validator: jsonschema.protocols.Validator,
) -> None:
    """The schema actually rejects something, not just accepts everything."""

    source, test = _sample_trees("contract")
    payload = compare(source, test).to_dict()
    del payload["schema_version"]
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(payload)


def test_an_unknown_top_level_key_fails_validation(
    validator: jsonschema.protocols.Validator,
) -> None:
    """The closed design is actually closed: an extra key is rejected."""

    source, test = _sample_trees("contract")
    payload = compare(source, test).to_dict()
    payload["spam"] = 1
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(payload)


def test_a_reserved_change_kind_is_not_yet_in_the_enum(
    validator: jsonschema.protocols.Validator,
) -> None:
    """``split``/``merge`` are reserved (1.1, ADR-0009), not accepted in 2.0.

    A schema that already accepted them would silently stop being a freeze:
    a 1.0 consumer validating a payload with a kind it does not understand
    should see the schema reject it, not wave it through.
    """

    source, test = _sample_trees("contract")
    payload = compare(source, test).to_dict()
    assert payload["changes"], "the sample pair must produce at least one change"
    payload["changes"][0]["kind"] = "split"
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(payload)
