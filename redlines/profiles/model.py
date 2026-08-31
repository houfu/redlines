"""Frozen dataclasses for the structure profile format (ADR-0006, ADR-0028)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

LABEL_STYLES = ("decimal", "alpha", "roman", "word")
LABEL_DEPTH_MODES = ("arithmetic", "stack")
ROLE_MATCH_KINDS = ("heading", "ancestor_heading", "parent_role")


@dataclass(frozen=True, slots=True)
class LabelPattern:
    """A pattern that recognises a leading label on a paragraph or list item.

    Patterns are tried in the order they appear in the profile; that order
    is the precedence a reader uses when more than one pattern could match.
    """

    name: str
    pattern: str
    style: str
    depth_mode: str = "stack"

    def compiled(self) -> re.Pattern[str]:
        return re.compile(self.pattern)


@dataclass(frozen=True, slots=True)
class HeadingReset:
    """A heading that opens a new section and clears the label-depth stack."""

    name: str
    pattern: str

    def compiled(self) -> re.Pattern[str]:
        return re.compile(self.pattern)


@dataclass(frozen=True, slots=True)
class HeadingRule:
    """General heuristics for recognising a short line as a heading."""

    max_words: int = 8
    allow_all_caps: bool = True
    allow_title_case: bool = True
    forbid_terminal_punctuation: bool = True


@dataclass(frozen=True, slots=True)
class RoleRule:
    """A rule assigning a semantic role (ADR-0005) to blocks.

    ``match`` selects how the rule applies:
    - ``heading``: the block is a heading whose text matches ``pattern``.
    - ``ancestor_heading``: the block has an ancestor heading matching
      ``pattern`` (e.g. everything under a "Schedule" heading).
    - ``parent_role``: the block's immediate parent already carries the
      role named in ``parent_role`` (e.g. items under a definitions block).
    """

    role: str
    match: str
    pattern: str | None = None
    parent_role: str | None = None

    def compiled(self) -> re.Pattern[str]:
        if self.pattern is None:
            raise ValueError(f"role rule {self.role!r} has no pattern to compile")
        return re.compile(self.pattern)


@dataclass(frozen=True, slots=True)
class SpanExtractor:
    """A regex extracting a semantic span (ADR-0005) from block text."""

    type: str
    pattern: str
    group: int = 0

    def compiled(self) -> re.Pattern[str]:
        return re.compile(self.pattern)


@dataclass(frozen=True, slots=True)
class Profile:
    """A validated structure profile: how a reader turns text into a labelled tree."""

    name: str
    description: str = ""
    label_patterns: tuple[LabelPattern, ...] = field(default_factory=tuple)
    heading_resets: tuple[HeadingReset, ...] = field(default_factory=tuple)
    heading_rule: HeadingRule = field(default_factory=HeadingRule)
    role_rules: tuple[RoleRule, ...] = field(default_factory=tuple)
    span_extractors: tuple[SpanExtractor, ...] = field(default_factory=tuple)
