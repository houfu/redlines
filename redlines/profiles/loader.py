"""Load structure profiles from a file, raw YAML text, or a mapping (R1e).

The on-disk format is YAML (ADR-0028). Every entry point ends up validating
a plain mapping against the same rules, so a profile authored as a Python
dict at call time is validated exactly as strictly as one loaded from disk.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from .errors import ProfileError
from .model import (
    LABEL_DEPTH_MODES,
    LABEL_STYLES,
    ROLE_MATCH_KINDS,
    HeadingReset,
    HeadingRule,
    LabelPattern,
    Profile,
    RoleRule,
    SpanExtractor,
)

_TOP_LEVEL_KEYS = {
    "name",
    "description",
    "label_patterns",
    "heading_resets",
    "heading_rule",
    "role_rules",
    "span_extractors",
}
_HEADING_RULE_KEYS = {
    "max_words",
    "allow_all_caps",
    "allow_title_case",
    "forbid_terminal_punctuation",
}
_LABEL_PATTERN_KEYS = {"name", "pattern", "style", "depth_mode"}
_HEADING_RESET_KEYS = {"name", "pattern"}
_ROLE_RULE_KEYS = {"role", "match", "pattern", "parent_role"}
_SPAN_EXTRACTOR_KEYS = {"type", "pattern", "group"}


def load_profile(source: str | Path | Mapping[str, Any]) -> Profile:
    """Load a profile from a mapping, a ``.yaml``/``.yml`` file path, or raw YAML text.

    A plain ``str`` that names an existing file on disk is read as that
    file; any other string is parsed as YAML text directly. This dispatch
    is meant for trusted, caller-controlled sources such as a CLI
    ``--profile`` argument or a path built in code. A caller that already
    holds text it did not choose (an MCP tool argument, the site's paste
    box) should call `parse_profile_yaml` directly, so a crafted string can
    never be mistaken for a path to a file already on disk.

    **A profile is trusted input, not sanitised input.** Its patterns are
    regular expressions that a reader will later run against document text
    with Python's backtracking `re` engine, where a short, perfectly valid
    pattern such as ``(a+)+$`` takes time exponential in the length of the
    text. Validation checks that every pattern *compiles*; it cannot check
    that one *terminates*, and the standard library gives no way to bound a
    match once it starts. Accept a profile from whoever you would let run
    code in the same process. Anything else -- a public paste box, an
    untrusted model's output -- needs a resource boundary around whatever
    runs the patterns (a subprocess or worker that can be killed), which is
    a property of the caller's deployment, not something this function can
    provide. Loading itself is cheap and safe: nothing here matches.
    """
    if isinstance(source, Mapping):
        return profile_from_mapping(source)
    if isinstance(source, Path):
        return _load_yaml_file(source)
    if isinstance(source, str):
        if _looks_like_a_path(source):
            candidate = Path(source)
            try:
                is_file = candidate.is_file()
            except OSError:
                is_file = False
            if is_file:
                return _load_yaml_file(candidate)
        return parse_profile_yaml(source)
    raise TypeError(
        f"Cannot load a profile from {type(source).__name__!r}; "
        "expected a file path, YAML text, or a mapping."
    )


def _looks_like_a_path(source: str) -> bool:
    """Cheaply rule out multi-line or overlong strings before touching the filesystem.

    A real YAML *file* never has these written to the profile text, only
    used as its own path, so newlines or excessive length are enough to
    know this is pasted/raw YAML text, not a path -- without needing to
    stat() it (which can itself raise on a too-long "path").
    """
    return "\n" not in source and len(source) <= 255


class _StrictSafeLoader(yaml.SafeLoader):
    """`yaml.SafeLoader`, but a repeated key is an error rather than the last one winning.

    Plain YAML resolves ``pattern: one`` followed by ``pattern: two`` to
    ``two``, silently. In a settings file that is merely surprising; in a
    file of match rules it means a profile can behave differently from the
    way it reads, with the losing line sitting right there in the document.
    """

    def construct_mapping(
        self, node: yaml.MappingNode, deep: bool = False
    ) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    "while constructing a profile",
                    node.start_mark,
                    f"duplicate key {key!r}",
                    key_node.start_mark,
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def parse_profile_yaml(text: str) -> Profile:
    """Parse raw YAML text into a validated `Profile`.

    Parsing is safe in the `yaml.safe_load` sense -- no arbitrary Python
    objects are constructed -- but see `load_profile` on why a profile is
    still trusted input.
    """
    try:
        # Safe despite the name: _StrictSafeLoader derives from SafeLoader,
        # so no tag can construct an arbitrary Python object.
        mapping = yaml.load(text, Loader=_StrictSafeLoader)  # noqa: S506
    except yaml.YAMLError as exc:
        raise ProfileError([f"invalid YAML: {exc}"]) from exc
    if mapping is None:
        mapping = {}
    return profile_from_mapping(mapping)


def profile_from_mapping(mapping: Mapping[str, Any]) -> Profile:
    """Validate a plain mapping against the profile format and build a `Profile`."""
    if not isinstance(mapping, Mapping):
        raise ProfileError(
            [f"a profile must be a mapping, got {type(mapping).__name__}"]
        )

    errors: list[str] = []
    _check_unknown_keys(mapping, _TOP_LEVEL_KEYS, "", errors)

    name = _require_str(mapping, "name", errors)
    description = _optional_str(mapping, "description", "", errors)

    label_patterns = tuple(
        pattern
        for pattern in (
            _build_label_pattern(item, f"label_patterns[{i}]", errors)
            for i, item in enumerate(
                _require_list_of_mappings(mapping, "label_patterns", errors)
            )
        )
        if pattern is not None
    )
    heading_resets = tuple(
        reset
        for reset in (
            _build_heading_reset(item, f"heading_resets[{i}]", errors)
            for i, item in enumerate(
                _require_list_of_mappings(mapping, "heading_resets", errors)
            )
        )
        if reset is not None
    )
    heading_rule = _build_heading_rule(
        mapping.get("heading_rule", {}), "heading_rule", errors
    )
    role_rules = tuple(
        rule
        for rule in (
            _build_role_rule(item, f"role_rules[{i}]", errors)
            for i, item in enumerate(
                _require_list_of_mappings(mapping, "role_rules", errors)
            )
        )
        if rule is not None
    )
    span_extractors = tuple(
        extractor
        for extractor in (
            _build_span_extractor(item, f"span_extractors[{i}]", errors)
            for i, item in enumerate(
                _require_list_of_mappings(mapping, "span_extractors", errors)
            )
        )
        if extractor is not None
    )

    if errors:
        raise ProfileError(errors)

    assert name is not None  # a missing name is already recorded in errors, above
    return Profile(
        name=name,
        description=description or "",
        label_patterns=label_patterns,
        heading_resets=heading_resets,
        heading_rule=heading_rule,
        role_rules=role_rules,
        span_extractors=span_extractors,
    )


def _load_yaml_file(path: Path) -> Profile:
    if path.suffix.lower() not in (".yaml", ".yml"):
        raise ProfileError([f"{path}: only .yaml/.yml profile files are supported"])
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProfileError([f"{path}: could not read file ({exc})"]) from exc
    return parse_profile_yaml(text)


# --- field-level helpers -----------------------------------------------------


def _check_unknown_keys(
    mapping: Mapping[str, Any], allowed: set[str], path: str, errors: list[str]
) -> None:
    for key in mapping:
        if key not in allowed:
            where = f"{path}." if path else ""
            errors.append(f"{where}{key}: unknown field")


def _require_str(mapping: Mapping[str, Any], key: str, errors: list[str]) -> str | None:
    if key not in mapping:
        errors.append(f"{key}: required field is missing")
        return None
    value = mapping[key]
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{key}: must be a non-empty string")
        return None
    return value


def _optional_str(
    mapping: Mapping[str, Any], key: str, default: str, errors: list[str]
) -> str:
    if key not in mapping:
        return default
    value = mapping[key]
    if not isinstance(value, str):
        errors.append(f"{key}: must be a string")
        return default
    return value


def _require_list_of_mappings(
    mapping: Mapping[str, Any], key: str, errors: list[str]
) -> Sequence[Mapping[str, Any]]:
    if key not in mapping:
        return ()
    value = mapping[key]
    if not isinstance(value, list):
        errors.append(f"{key}: must be a list of mappings")
        return ()
    items: list[Mapping[str, Any]] = []
    for i, item in enumerate(value):
        if not isinstance(item, Mapping):
            errors.append(f"{key}[{i}]: must be a mapping")
            continue
        items.append(item)
    return items


def _compile_or_error(pattern: str, path: str, errors: list[str]) -> bool:
    try:
        re.compile(pattern)
    except re.error as exc:
        errors.append(f"{path}.pattern: invalid regular expression ({exc})")
        return False
    return True


def _build_label_pattern(
    item: Mapping[str, Any], path: str, errors: list[str]
) -> LabelPattern | None:
    _check_unknown_keys(item, _LABEL_PATTERN_KEYS, path, errors)
    ok = True

    name = item.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append(f"{path}.name: must be a non-empty string")
        ok = False

    pattern = item.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        errors.append(f"{path}.pattern: must be a non-empty string")
        ok = False
    elif not _compile_or_error(pattern, path, errors):
        ok = False

    style = item.get("style")
    if style not in LABEL_STYLES:
        errors.append(f"{path}.style: must be one of {sorted(LABEL_STYLES)}")
        ok = False

    depth_mode = item.get("depth_mode", "stack")
    if depth_mode not in LABEL_DEPTH_MODES:
        errors.append(f"{path}.depth_mode: must be one of {sorted(LABEL_DEPTH_MODES)}")
        ok = False

    if not ok:
        return None
    assert isinstance(name, str)
    assert isinstance(pattern, str)
    assert isinstance(style, str)
    assert isinstance(depth_mode, str)
    return LabelPattern(name=name, pattern=pattern, style=style, depth_mode=depth_mode)


def _build_heading_reset(
    item: Mapping[str, Any], path: str, errors: list[str]
) -> HeadingReset | None:
    _check_unknown_keys(item, _HEADING_RESET_KEYS, path, errors)
    ok = True

    name = item.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append(f"{path}.name: must be a non-empty string")
        ok = False

    pattern = item.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        errors.append(f"{path}.pattern: must be a non-empty string")
        ok = False
    elif not _compile_or_error(pattern, path, errors):
        ok = False

    if not ok:
        return None
    assert isinstance(name, str)
    assert isinstance(pattern, str)
    return HeadingReset(name=name, pattern=pattern)


def _build_heading_rule(item: Any, path: str, errors: list[str]) -> HeadingRule:
    if not isinstance(item, Mapping):
        errors.append(f"{path}: must be a mapping")
        return HeadingRule()
    _check_unknown_keys(item, _HEADING_RULE_KEYS, path, errors)

    defaults = HeadingRule()
    max_words = item.get("max_words", defaults.max_words)
    if not isinstance(max_words, int) or isinstance(max_words, bool) or max_words < 1:
        errors.append(f"{path}.max_words: must be a positive integer")
        max_words = defaults.max_words

    bool_fields = {}
    for key in ("allow_all_caps", "allow_title_case", "forbid_terminal_punctuation"):
        value = item.get(key, getattr(defaults, key))
        if not isinstance(value, bool):
            errors.append(f"{path}.{key}: must be true or false")
            value = getattr(defaults, key)
        bool_fields[key] = value

    return HeadingRule(max_words=max_words, **bool_fields)


def _build_role_rule(
    item: Mapping[str, Any], path: str, errors: list[str]
) -> RoleRule | None:
    _check_unknown_keys(item, _ROLE_RULE_KEYS, path, errors)
    ok = True

    role = item.get("role")
    if not isinstance(role, str) or not role.strip():
        errors.append(f"{path}.role: must be a non-empty string")
        ok = False

    match = item.get("match")
    if match not in ROLE_MATCH_KINDS:
        errors.append(f"{path}.match: must be one of {sorted(ROLE_MATCH_KINDS)}")
        ok = False
        match = None

    pattern = item.get("pattern")
    parent_role = item.get("parent_role")

    if match in ("heading", "ancestor_heading"):
        if not isinstance(pattern, str) or not pattern:
            errors.append(
                f"{path}.pattern: required and must be a non-empty string when match={match!r}"
            )
            ok = False
        elif not _compile_or_error(pattern, path, errors):
            ok = False
        if parent_role is not None:
            errors.append(f"{path}.parent_role: must not be set when match={match!r}")
            ok = False
    elif match == "parent_role":
        if not isinstance(parent_role, str) or not parent_role.strip():
            errors.append(
                f"{path}.parent_role: required and must be a non-empty string when match='parent_role'"
            )
            ok = False
        if pattern is not None:
            errors.append(f"{path}.pattern: must not be set when match='parent_role'")
            ok = False

    if not ok:
        return None
    assert isinstance(role, str)
    assert isinstance(match, str)
    return RoleRule(
        role=role,
        match=match,
        pattern=pattern if isinstance(pattern, str) else None,
        parent_role=parent_role if isinstance(parent_role, str) else None,
    )


def _build_span_extractor(
    item: Mapping[str, Any], path: str, errors: list[str]
) -> SpanExtractor | None:
    _check_unknown_keys(item, _SPAN_EXTRACTOR_KEYS, path, errors)
    ok = True

    span_type = item.get("type")
    if not isinstance(span_type, str) or not span_type.strip():
        errors.append(f"{path}.type: must be a non-empty string")
        ok = False

    pattern = item.get("pattern")
    compiled: re.Pattern[str] | None = None
    if not isinstance(pattern, str) or not pattern:
        errors.append(f"{path}.pattern: must be a non-empty string")
        ok = False
    elif not _compile_or_error(pattern, path, errors):
        ok = False
    else:
        compiled = re.compile(pattern)

    group = item.get("group", 0)
    if not isinstance(group, int) or isinstance(group, bool) or group < 0:
        errors.append(f"{path}.group: must be a non-negative integer")
        ok = False
    elif compiled is not None and group > compiled.groups:
        errors.append(
            f"{path}.group: pattern only has {compiled.groups} capturing group(s), got {group}"
        )
        ok = False

    if not ok:
        return None
    assert isinstance(span_type, str)
    assert isinstance(pattern, str)
    return SpanExtractor(type=span_type, pattern=pattern, group=group)
