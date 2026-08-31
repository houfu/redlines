"""Tests for the structure profile format, loader and validator (issue #100)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from redlines.profiles import (
    Profile,
    ProfileError,
    load_profile,
    parse_profile_yaml,
    profile_from_mapping,
    profile_schema_text,
)
from redlines.profiles.loader import (
    _HEADING_RESET_KEYS,
    _HEADING_RULE_KEYS,
    _LABEL_PATTERN_KEYS,
    _ROLE_RULE_KEYS,
    _SPAN_EXTRACTOR_KEYS,
    _TOP_LEVEL_KEYS,
)
from redlines.profiles.model import (
    LABEL_DEPTH_MODES,
    LABEL_STYLES,
    ROLE_MATCH_KINDS,
    HeadingRule,
    LabelPattern,
    SpanExtractor,
)

FIXTURES = Path(__file__).parent / "profiles"
CONTRACT_YAML = FIXTURES / "example_contract.yaml"
GENERIC_YAML = FIXTURES / "example_generic.yaml"


# --- loading from each of the three sources agrees -------------------------


def test_load_profile_from_path() -> None:
    profile = load_profile(CONTRACT_YAML)
    assert isinstance(profile, Profile)
    assert profile.name == "example-contract"
    assert len(profile.label_patterns) == 3
    assert len(profile.heading_resets) == 1
    assert len(profile.role_rules) == 5
    assert len(profile.span_extractors) == 4


def test_load_profile_from_existing_file_string_path() -> None:
    profile = load_profile(str(CONTRACT_YAML))
    assert profile.name == "example-contract"


def test_load_profile_from_raw_yaml_text_sniffed_as_text() -> None:
    text = CONTRACT_YAML.read_text(encoding="utf-8")
    profile = load_profile(text)
    assert profile.name == "example-contract"


def test_parse_profile_yaml_matches_load_profile() -> None:
    text = CONTRACT_YAML.read_text(encoding="utf-8")
    assert parse_profile_yaml(text) == load_profile(CONTRACT_YAML)


def test_load_profile_from_mapping() -> None:
    profile = load_profile(
        {
            "name": "inline",
            "label_patterns": [
                {"name": "decimal", "pattern": r"^(\d+)\.\s+", "style": "decimal"}
            ],
        }
    )
    assert profile.name == "inline"
    assert profile.label_patterns[0].style == "decimal"
    assert profile.label_patterns[0].depth_mode == "stack"  # default applied


def test_profile_from_mapping_matches_load_profile() -> None:
    mapping = {"name": "same"}
    assert profile_from_mapping(mapping) == load_profile(mapping)


def test_load_profile_rejects_unsupported_type() -> None:
    with pytest.raises(TypeError):
        load_profile(123)  # type: ignore[arg-type]


# --- minimal ("generic") profile: everything optional except name ----------


def test_minimal_profile_applies_defaults() -> None:
    profile = load_profile(GENERIC_YAML)
    assert profile.name == "example-generic"
    assert profile.label_patterns == ()
    assert profile.heading_resets == ()
    assert profile.role_rules == ()
    assert profile.span_extractors == ()
    assert profile.heading_rule.max_words == 8
    assert profile.heading_rule.allow_all_caps is True


def test_name_only_mapping_is_valid() -> None:
    profile = load_profile({"name": "bare"})
    assert profile.description == ""


def test_empty_yaml_document_is_reported_as_missing_name() -> None:
    with pytest.raises(ProfileError) as excinfo:
        parse_profile_yaml("")
    assert any("name" in error for error in excinfo.value.errors)


# --- compiled() compiles the stored pattern ---------------------------------


def test_label_pattern_compiles_and_matches() -> None:
    profile = load_profile(CONTRACT_YAML)
    decimal = next(p for p in profile.label_patterns if p.name == "decimal")
    match = decimal.compiled().match("1.2 Some clause text")
    assert match is not None
    assert match.group(1) == "1.2"


def test_span_extractor_group_extracts_expected_text() -> None:
    profile = load_profile(CONTRACT_YAML)
    defined_term = next(s for s in profile.span_extractors if s.type == "defined_term")
    match = defined_term.compiled().search('"Confidential Information" means any data.')
    assert match is not None
    assert match.group(defined_term.group) == "Confidential Information"


# --- validation failures ----------------------------------------------------


def test_missing_name_is_rejected() -> None:
    with pytest.raises(ProfileError) as excinfo:
        load_profile({})
    assert any("name" in error for error in excinfo.value.errors)


def test_unknown_top_level_key_is_rejected() -> None:
    with pytest.raises(ProfileError) as excinfo:
        load_profile({"name": "x", "typo_field": True})
    assert any("typo_field" in error for error in excinfo.value.errors)


def test_bad_regex_is_rejected_with_field_path() -> None:
    with pytest.raises(ProfileError) as excinfo:
        load_profile(
            {
                "name": "x",
                "label_patterns": [{"name": "bad", "pattern": "(unclosed", "style": "decimal"}],
            }
        )
    assert any("label_patterns[0].pattern" in error for error in excinfo.value.errors)


def test_invalid_label_style_is_rejected() -> None:
    with pytest.raises(ProfileError) as excinfo:
        load_profile(
            {
                "name": "x",
                "label_patterns": [{"name": "n", "pattern": r"^\d+", "style": "hexadecimal"}],
            }
        )
    assert any("label_patterns[0].style" in error for error in excinfo.value.errors)


def test_role_rule_heading_requires_pattern() -> None:
    with pytest.raises(ProfileError) as excinfo:
        load_profile({"name": "x", "role_rules": [{"role": "definitions", "match": "heading"}]})
    assert any("role_rules[0].pattern" in error for error in excinfo.value.errors)


def test_role_rule_parent_role_requires_parent_role_field() -> None:
    with pytest.raises(ProfileError) as excinfo:
        load_profile({"name": "x", "role_rules": [{"role": "definition", "match": "parent_role"}]})
    assert any("role_rules[0].parent_role" in error for error in excinfo.value.errors)


def test_role_rule_parent_role_rejects_pattern() -> None:
    with pytest.raises(ProfileError) as excinfo:
        load_profile(
            {
                "name": "x",
                "role_rules": [
                    {
                        "role": "definition",
                        "match": "parent_role",
                        "parent_role": "definitions",
                        "pattern": "should not be here",
                    }
                ],
            }
        )
    assert any("role_rules[0].pattern" in error for error in excinfo.value.errors)


def test_span_extractor_group_out_of_range_is_rejected() -> None:
    with pytest.raises(ProfileError) as excinfo:
        load_profile(
            {
                "name": "x",
                "span_extractors": [{"type": "date", "pattern": r"\d{4}", "group": 1}],
            }
        )
    assert any("span_extractors[0].group" in error for error in excinfo.value.errors)


def test_multiple_errors_are_all_reported() -> None:
    with pytest.raises(ProfileError) as excinfo:
        load_profile(
            {
                "label_patterns": [{"name": "n", "pattern": "(bad", "style": "nope"}],
                "role_rules": [{"role": "x", "match": "nonsense"}],
            }
        )
    # missing name + bad pattern + bad style + bad match = at least 4 problems
    assert len(excinfo.value.errors) >= 4


def test_malformed_yaml_is_rejected() -> None:
    with pytest.raises(ProfileError):
        parse_profile_yaml("a: {b: c")  # unclosed flow mapping


def test_duplicate_top_level_key_is_rejected() -> None:
    """Plain YAML keeps the last silently; in a rule file that hides a live line."""
    with pytest.raises(ProfileError, match="duplicate key"):
        parse_profile_yaml("name: first\nname: second")


def test_duplicate_key_inside_a_rule_is_rejected() -> None:
    with pytest.raises(ProfileError, match="duplicate key"):
        parse_profile_yaml(
            "name: x\n"
            "label_patterns:\n"
            "  - name: decimal\n"
            "    pattern: '^one'\n"
            "    pattern: '^two'\n"
            "    style: decimal\n"
        )


def test_only_yaml_file_extension_is_accepted() -> None:
    with pytest.raises(ProfileError):
        load_profile(Path(__file__))  # a .py file


def test_profile_from_mapping_rejects_non_mapping() -> None:
    with pytest.raises(ProfileError):
        profile_from_mapping(["not", "a", "mapping"])  # type: ignore[arg-type]


# --- order is part of the format's meaning ----------------------------------


def test_role_rules_keep_their_declared_order() -> None:
    """A block carries one role, so role_rules order is precedence (first match wins)."""
    profile = load_profile(
        {
            "name": "ordered",
            "role_rules": [
                {"role": "schedule", "match": "heading", "pattern": "^Schedule"},
                {"role": "clause", "match": "heading", "pattern": "^S"},
            ],
        }
    )
    assert [rule.role for rule in profile.role_rules] == ["schedule", "clause"]


def test_span_extractors_keep_their_declared_order() -> None:
    """A block carries many spans, so every extractor runs; order is only emission order."""
    profile = load_profile(
        {
            "name": "ordered",
            "span_extractors": [
                {"type": "date", "pattern": r"\d{4}"},
                {"type": "amount", "pattern": r"\$\d+"},
            ],
        }
    )
    assert [extractor.type for extractor in profile.span_extractors] == ["date", "amount"]


# --- the published JSON Schema is well-formed and matches the model --------

# One known-good entry per definition, and the top-level key it lives under.
# Used to check the schema's `required` lists against what the loader really
# enforces, rather than restating them.
_EXEMPLARS: dict[str, tuple[str, dict[str, object]]] = {
    "labelPattern": (
        "label_patterns",
        {"name": "decimal", "pattern": r"^(\d+)\.", "style": "decimal"},
    ),
    "headingReset": ("heading_resets", {"name": "schedule", "pattern": "^Schedule"}),
    "roleRule": ("role_rules", {"role": "schedule", "match": "heading", "pattern": "^Schedule"}),
    "spanExtractor": ("span_extractors", {"type": "date", "pattern": r"\d{4}"}),
}


def _schema() -> dict[str, Any]:
    schema: dict[str, Any] = json.loads(profile_schema_text())
    return schema


def test_schema_json_is_valid_json() -> None:
    schema = _schema()
    assert schema["title"] == "Redlines Structure Profile"
    assert schema["required"] == ["name"]
    assert set(schema["properties"]) == _TOP_LEVEL_KEYS


def test_schema_ships_inside_the_installed_package() -> None:
    """profile_schema_text reads from the package, so a missing wheel file fails here."""
    assert profile_schema_text().startswith("{")


def test_schema_definition_keys_match_the_validator() -> None:
    definitions = _schema()["definitions"]
    expected = {
        "labelPattern": _LABEL_PATTERN_KEYS,
        "headingReset": _HEADING_RESET_KEYS,
        "headingRule": _HEADING_RULE_KEYS,
        "roleRule": _ROLE_RULE_KEYS,
        "spanExtractor": _SPAN_EXTRACTOR_KEYS,
    }
    for definition_name, keys in expected.items():
        definition = definitions[definition_name]
        assert set(definition["properties"]) == keys, definition_name
        assert definition["additionalProperties"] is False, definition_name


def test_schema_enums_match_the_model_vocabularies() -> None:
    definitions = _schema()["definitions"]
    label_pattern = definitions["labelPattern"]["properties"]
    assert set(label_pattern["style"]["enum"]) == set(LABEL_STYLES)
    assert set(label_pattern["depth_mode"]["enum"]) == set(LABEL_DEPTH_MODES)
    assert set(definitions["roleRule"]["properties"]["match"]["enum"]) == set(ROLE_MATCH_KINDS)


def test_schema_defaults_match_the_dataclass_defaults() -> None:
    definitions = _schema()["definitions"]
    heading_rule = HeadingRule()
    for field, prop in definitions["headingRule"]["properties"].items():
        assert prop["default"] == getattr(heading_rule, field), field
    assert definitions["labelPattern"]["properties"]["depth_mode"]["default"] == (
        LabelPattern(name="n", pattern="x", style="decimal").depth_mode
    )
    assert definitions["spanExtractor"]["properties"]["group"]["default"] == (
        SpanExtractor(type="t", pattern="x").group
    )


# Every shape a role rule can take, and whether it is legal. The loader and
# the schema's conditional branches must agree on all of them -- the schema
# once accepted rules the loader rejects, because it only required role+match.
_ROLE_RULE_CASES: list[tuple[str, dict[str, object], bool]] = [
    ("heading with pattern", {"role": "r", "match": "heading", "pattern": "^x"}, True),
    ("heading without pattern", {"role": "r", "match": "heading"}, False),
    (
        "heading with parent_role",
        {"role": "r", "match": "heading", "pattern": "^x", "parent_role": "p"},
        False,
    ),
    (
        "ancestor_heading with pattern",
        {"role": "r", "match": "ancestor_heading", "pattern": "^x"},
        True,
    ),
    ("ancestor_heading without pattern", {"role": "r", "match": "ancestor_heading"}, False),
    ("parent_role with parent_role", {"role": "r", "match": "parent_role", "parent_role": "p"}, True),
    ("parent_role without parent_role", {"role": "r", "match": "parent_role"}, False),
    (
        "parent_role with pattern",
        {"role": "r", "match": "parent_role", "parent_role": "p", "pattern": "^x"},
        False,
    ),
]


@pytest.mark.parametrize(
    ("label", "rule", "is_valid"),
    [pytest.param(label, rule, ok, id=label) for label, rule, ok in _ROLE_RULE_CASES],
)
def test_role_rule_branches_load_exactly_when_they_should(
    label: str, rule: dict[str, object], is_valid: bool
) -> None:
    """Acceptance and rejection, both directions -- not just that bad input fails."""
    profile = {"name": "x", "role_rules": [rule]}
    if is_valid:
        assert load_profile(profile).role_rules[0].role == "r"
    else:
        with pytest.raises(ProfileError):
            load_profile(profile)


def test_schema_encodes_the_role_rule_conditionals_the_loader_enforces() -> None:
    """A rule the schema calls valid must load; the schema must not be laxer than the code.

    There is no jsonschema dependency to validate documents with (ADR-0028),
    so this checks the conditional branches structurally instead.
    """
    branches = _schema()["definitions"]["roleRule"]["allOf"]
    by_match: dict[str, dict[str, Any]] = {}
    for branch in branches:
        match_schema = branch["if"]["properties"]["match"]
        for kind in match_schema.get("enum", [match_schema.get("const")]):
            by_match[kind] = branch["then"]

    assert set(by_match) == set(ROLE_MATCH_KINDS), "every match kind needs a branch"
    for kind in ("heading", "ancestor_heading"):
        assert by_match[kind]["required"] == ["pattern"]
        assert by_match[kind]["not"]["required"] == ["parent_role"]
    assert by_match["parent_role"]["required"] == ["parent_role"]
    assert by_match["parent_role"]["not"]["required"] == ["pattern"]


@pytest.mark.parametrize("definition_name", sorted(_EXEMPLARS))
def test_schema_required_fields_are_the_ones_the_validator_enforces(definition_name: str) -> None:
    """Dropping any field the schema calls required must actually fail validation."""
    definition = _schema()["definitions"][definition_name]
    key, exemplar = _EXEMPLARS[definition_name]

    load_profile({"name": "x", key: [exemplar]})  # the exemplar itself is valid

    for required_field in definition["required"]:
        incomplete = {k: v for k, v in exemplar.items() if k != required_field}
        with pytest.raises(ProfileError, match=required_field):
            load_profile({"name": "x", key: [incomplete]})
