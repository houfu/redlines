"""The semantic pass: roles and spans over a finished block tree (#104, R1b, R1c).

`apply_semantics` is PRD § 6b's sixth stage. The five mechanical stages belong
to a reader and run on *text*; this one runs on the *tree* a reader produced,
and it is the only place a block acquires a `role` or a `Span`::

    from redlines.profiles import builtin_profile
    from redlines.readers import reader_for
    from redlines.semantic import apply_semantics

    profile = builtin_profile("contract")
    tree = reader_for("text").read(source, profile=profile)
    tree = apply_semantics(tree, profile)

Those two lines are what `redlines.pipeline.read_document` composes -- pick a
profile, read, interpret -- so ``read_document(source, format="text")`` is the
same pipeline with the profile defaulted. Readers themselves never call this
pass: a reader produces structure and stops, and the tree it returns carries no
role and no span until this module has run over it.

It is pure: the tree that goes in is never mutated, the tree that comes out is
new, and running it twice over the same tree gives the same tree the first run
gave (N1). It holds no state between calls.

**Everything it does comes from the profile** (ADR-0006), with one named
exception. `Profile.role_rules` assign roles, `Profile.span_extractors` emit
spans, and a profile that declares neither leaves the tree exactly as it found
it. The exception is PRD § 6b's definitions heuristic -- *quoted term,
"means", text* -- which no profile can express, because it is a majority vote
over a section's members and a rule only ever sees one block (a ``text`` rule
can name the shape, ADR-0031, but not "more than half of them"). It is written
here instead, gated behind the profile naming the `definitions` or
`definition` role, and every block it touches records `attrs["semantic"]`
saying which path fired.

Roles
-----

Roles are assigned **top-down**, in document order, so a block's parent and
ancestors already carry theirs by the time its own rules are tried -- which is
what makes a ``parent_role`` rule work. Each rule kind answers a question
about a different block:

- ``heading`` -- *this* block is a heading whose text matches.
- ``text`` -- *this* block's own text matches (ADR-0031).
- ``label`` -- *this* block's own label matches; a block with no label never
  does (ADR-0031).
- ``parent_role`` -- the block's immediate parent carries a role.
- ``ancestor_heading`` -- the block sits under a heading that matches, at any
  depth.

Any kind but ``heading`` may also carry a ``kind`` filter, and then applies
only to blocks of that structural kind.

**Rules are tried in profile order and the first match wins** -- the schema's
"order is precedence" -- with the one exception ADR-0028 names, and only that
one. ``ancestor_heading`` rules are resolved from the block outwards first, so
a rule matching the *nearest* heading beats one matching a heading further out
however the two are listed -- a "Conclusion" inside "My decision" gives its
paragraphs the conclusion role either way -- and list order only breaks a tie
between rules matching that same heading. Nothing re-orders the other four
kinds: a ``parent_role`` or ``ancestor_heading`` rule listed above a
``heading``, ``text`` or ``label`` rule takes precedence over it, so an author
can order rules to mean what the schema says they mean.
A rule that matches nothing leaves the block's existing role alone,
so a role a reader or an earlier pass put there survives a profile that has
nothing to say about it.

A ``heading`` or ``ancestor_heading`` pattern is *searched* (anchor it with
``^`` if you mean the start) against the heading's own ``text``, which the
reader has already stripped of the label -- so ``'^Background'`` matches the
heading ``3. Background``. Where that fails and the heading carries a label,
the pattern is tried a second time against the heading **as written**,
``label`` and ``text`` rejoined (`heading_line`). Without that second try the
commonest heading in a contract would be unreachable: a reader that reads
``SCHEDULE 1`` as the label ``Schedule 1`` leaves the heading's ``text``
empty, and ``'^schedule'`` would match nothing at all.

Under a heading
---------------

``ancestor_heading`` needs "under a heading" to mean something on more than
one tree shape, so `ancestor_headings` derives it from position the way
`redlines.blocks.heading_breadcrumb` derives the address breadcrumb
(ADR-0029) -- the role a block gets and the crumb a reader sees therefore
agree -- with one refinement the breadcrumb does not need, which is that a
flat run of headings nests by ``level``. Walking out from the block, at each
step:

- a **section whose first child is the heading** (what
  `redlines.readers.text.PlainTextReader` builds, and what the markdown reader
  builds to match) contributes that heading, because it precedes the block
  among its siblings;
- a **flat run of sibling headings** (`redlines.readers.ParagraphReader`, or a
  third-party reader that emits no containers) contributes the nearest
  preceding heading sibling and then every heading before it of a *strictly
  lower* ``level``, so ``# A`` / ``## B`` / paragraph gives ``(B, A)``;
- an ancestor that is **itself a heading block** holding its content
  contributes itself.

A heading is never under itself, and two headings at the same level never
nest, so ``# A`` / ``# B`` leaves B with no ancestor at all.

Spans
-----

Every extractor runs and every match is kept, in extractor order, with the
`SpanExtractor.group`'s own range as the span's offsets into the block's
``text``. Overlap between extractors is *not* an error and both spans are
kept: a range can honestly be a ``party`` and a ``defined_term`` at once, and
"Clauses 7.2 and 7.3" is two ``cross_reference`` spans found by two patterns.
The single rule is that a block carries **at most one span of a given type
over a given range**; where two extractors would produce that, the earlier one
in the profile wins. Spans already on the block are kept, first, and a new
span that duplicates one of them is dropped -- which is what makes a second
pass a no-op, and what keeps a span a reader emitted from the format itself
(markdown emphasis, ADR-0024) from being thrown away by a profile that knows
nothing about it.

A ``cross_reference`` span carries the referenced label in `Span.value`,
normalised the way a reader normalises a label -- whitespace collapsed, one
trailing full stop dropped -- so ``"clause 7.2."`` yields ``"7.2"`` and M2 can
say "cross-reference updated to follow renumbering" rather than "text
changed". Other span types leave ``value`` as ``None``: their text speaks for
itself.

Definitions (PRD § 6b)
----------------------

A definitions section is recognised two ways, and both give the section the
`definitions` role and its text-block members the `definition` role with a
``defined_term`` span:

1. **by heading** -- the section's heading matches the profile's own rule for
   the `definitions` role;
2. **by shape** -- more than half of the section's members contain the
   *quoted term, "means", text* shape (`DEFINITION_SHAPE_PATTERN`), or a lone
   member contains it twice, which is PRD § 6b's "definitions written as a
   run-on paragraph rather than a list": one block, several definitions in it,
   and a ``defined_term`` span on each.

Both paths are gated on the profile naming the `definitions` or `definition`
role, so a profile that has not asked for contract semantics (the built-in
``generic``) gets none.

What the pass recorded
----------------------

Every block the pass decided something about carries ``attrs["semantic"]``, a
plain JSON-serialisable mapping, for the same reason every reading stage
records what it decided (PRD § 6b): a wrong role is otherwise invisible.

- ``role`` -- the role assigned, and ``role_match`` how: one of the five
  profile match kinds, or ``definitions_heading`` / ``definitions_shape`` /
  ``definition_heading`` / ``definition_shape`` where the definitions rule
  above did it.
- ``role_rule`` -- the rule's position in the profile's ``role_rules``, or
  ``None`` for the definitions rule, which is not in the profile.
- ``matched`` (``text`` or ``heading_line`` for a heading rule; the substring
  the pattern found for a ``text`` rule), ``label`` (the label a ``label``
  rule matched), ``ancestor`` (the heading that decided) or ``parent_role``
  -- the evidence, by match kind -- and ``kind`` where the rule carried a
  filter.
- ``defined_terms`` -- how many definitions a `definition` block holds; more
  than one is the run-on paragraph.
- ``spans`` -- how many spans the block carries after the pass.

What the profile format cannot express
--------------------------------------

Reported here rather than closed by extending the format (ADR-0028):

- **No rule can look at more than one block.** A ``text`` rule can name the
  definition shape on a block (ADR-0031 closed the gap ADR-0028 deferred),
  but the definitions heuristic above decides a *section* by the shape of
  more than half its members, and no per-block rule can count. So it stays
  here, and it is the only rule that does. It takes the list position of the
  profile rule that names the role it assigns -- `definitions` for the
  section and its heading, `definition` for the members -- and is settled by
  list order like every other rule, so a ``clause`` rule listed after
  ``definition`` loses to it on every tree shape, and one listed before wins.
- **No rule can say "role the section this heading opens".** ``heading``
  labels the heading block and ``ancestor_heading`` labels what follows it, so
  on a tree that wraps both in a ``section`` the wrapper itself is left
  role-less. The definitions rule above is the one place that gap is filled,
  and only for `definitions`.
- **``parent_role`` cannot reach past a structural container.** The schema
  describes a block's parent as "for a block directly under a heading, that
  heading's block", which is not the shape either built-in reader produces: a
  clause's parent is the ``section``, not the ``heading``. A ``parent_role``
  rule written against the built-in profiles therefore fires only where a
  container itself carries a role.
- **A span is a range, not a record**, so a cross-reference keeps the label it
  cited and nothing about what it cites; and an extractor has one group, so
  the third reference in "clauses 7.2, 7.3 and 7.4" needs a third pattern.

Reading and then applying
-------------------------

There is deliberately no ``read_document`` convenience here. Composing the two
halves is two lines (above), and the interesting part is not the composition
but the policy -- which format a source is, which profile a format defaults to
(PRD § 6b: ``contract`` for plain text, ``markdown`` for ``.md``), and what to
do when detection returns nothing. That is the pipeline's decision, and the
pipeline is wave C's; putting a half-answer here would fix the policy in the
wrong module.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from .blocks import ROOT_PATH, Block, BlockKind, BlockTree, Span, block_at
from .profiles import Profile, RoleRule

__all__ = [
    "CROSS_REFERENCE_TYPE",
    "DEFINED_TERM_TYPE",
    "DEFINITIONS_ROLE",
    "DEFINITION_MEMBER_KINDS",
    "DEFINITION_ROLE",
    "DEFINITION_SHAPE_PATTERN",
    "ancestor_headings",
    "apply_semantics",
    "extract_spans",
    "heading_line",
]


DEFINITIONS_ROLE = "definitions"
"""The role a definitions section carries (`redlines.blocks.RECOMMENDED_ROLES`)."""

DEFINITION_ROLE = "definition"
"""The role one definition inside such a section carries.

The definitions heuristic is gated on a profile naming this role or
`DEFINITIONS_ROLE` in its ``role_rules``: a profile that has not asked for
definitions semantics does not get them behind its back.
"""

DEFINITION_MEMBER_KINDS: tuple[BlockKind, ...] = (
    BlockKind.PARAGRAPH,
    BlockKind.LIST_ITEM,
)
"""The block kinds a definitions section's *members* can be.

A definition is a piece of text, so only text-carrying blocks are considered
-- a nested ``section`` or a second ``heading`` under a definitions heading
keeps whatever role its own rules give it.
"""

DEFINITION_SHAPE_PATTERN = (
    r"[“\"]([^”\"\n]{1,120})[”\"]"
    r"\s+(?:means|shall mean|has the meaning|shall have the meaning)\b"
)
"""PRD § 6b's *quoted term, "means", text* shape; group 1 is the term.

Straight and curly quotes are both accepted, and deliberately not required to
pair, because a document that has been through a word processor and a PDF
extractor routinely mixes them. This is the one pattern in redlines that a
profile does not own, and the reason is stated in ADR-0028: all three role
match kinds are structural and none can look at the block's own text.
"""

DEFINED_TERM_TYPE = "defined_term"
"""The span type the definitions heuristic emits (`RECOMMENDED_SPAN_TYPES`)."""

CROSS_REFERENCE_TYPE = "cross_reference"
"""The one span type whose `Span.value` is filled in: the referenced label."""

_DEFINITION_SHAPE = re.compile(DEFINITION_SHAPE_PATTERN)
_WHITESPACE = re.compile(r"\s+")

_MATCH_HEADING = "heading"
_MATCH_ANCESTOR = "ancestor_heading"
_MATCH_PARENT_ROLE = "parent_role"
_MATCH_TEXT = "text"
_MATCH_LABEL = "label"


# --- addressing -------------------------------------------------------------


def heading_line(block: Block) -> str:
    """Return a heading the way the document wrote it: its label and its text.

    A reader strips a heading's label into `Block.label` and leaves the rest in
    `Block.text`, so ``SCHEDULE 1`` -- which is *all* label -- has no text at
    all. Rejoining the two is what lets a role pattern reach it. The separator
    is a single space, so punctuation the reader dropped after the label
    (``7.`` becomes the label ``7``) does not come back.

    :param block: any block; the label and text of a heading are what this is
        for.
    :return: ``"label text"``, ``"label"`` or ``"text"``, whichever the block
        has, with no surrounding whitespace.
    """
    return " ".join(part for part in (block.label, block.text) if part).strip()


def ancestor_headings(root: Block, path: str) -> tuple[Block, ...]:
    """Return the headings the block at ``path`` sits under, **nearest first**.

    The definition of "under a heading" this module uses, derived from position
    the way `redlines.blocks.heading_breadcrumb` derives its crumbs, so that it
    works on a tree of sections whose first child is a heading, on a flat run
    of sibling headings, and on a tree that nests content inside the heading
    block itself. The one refinement the breadcrumb does not need is that a
    flat run of headings nests by ``level``. See this module's docstring.

    Position in the result *is* the heading's distance from the block -- the
    first entry is the nearest -- which is what ADR-0028's "the nearest
    matching ancestor decides" is measured in. A container step that
    contributes two headings (a flat run nesting by ``level``) therefore
    contributes two distances, not one shared one.

    :param root: the document root.
    :param path: the address of the block to describe (ADR-0029).
    :return: the ancestor headings, nearest first; empty when the block sits
        under none.
    :raises ValueError: if ``path`` is not an address.
    :raises KeyError: if the tree has no block there.
    """
    found: list[Block] = []
    chain = _chain(root, path)
    for (parent, _), (child, position) in reversed(list(zip(chain, chain[1:]))):
        found.extend(
            _preceding_headings(
                parent.children,
                position,
                floor=child.level if child.kind is BlockKind.HEADING else None,
            )
        )
        if parent.kind is BlockKind.HEADING:
            # A heading holding its own content is an ancestor of it, one step
            # out, like any other parent.
            found.append(parent)
    return tuple(found)


def _chain(root: Block, path: str) -> tuple[tuple[Block, int], ...]:
    """Return ``(block, position)`` from ``root`` down to the block at ``path``.

    ``position`` is the block's index among *all* its parent's children, which
    is what the preceding-sibling rules need; the root's is ``-1``. Resolution
    goes through `redlines.blocks.block_at` one step at a time rather than
    re-implementing the address parser.
    """
    chain: list[tuple[Block, int]] = [(root, -1)]
    if path == ROOT_PATH:
        return tuple(chain)
    prefix = ""
    for step in path[1:].split("/") if path.startswith(ROOT_PATH) else [path]:
        prefix = f"{prefix}/{step}"
        child = block_at(root, prefix)
        parent = chain[-1][0]
        position = next(
            index
            for index, candidate in enumerate(parent.children)
            if candidate is child
        )
        chain.append((child, position))
    return tuple(chain)


def _preceding_headings(
    siblings: Sequence[Block], position: int, *, floor: int | None
) -> tuple[Block, ...]:
    """Return the heading siblings before ``position`` that contain it.

    Walking backwards, the nearest heading is taken and then only headings of a
    strictly lower ``level``, which is how a flat run of headings expresses
    nesting. ``floor`` starts at a *heading's* own level, so two headings at
    the same level never nest and a level-0 heading -- a reader that scores
    headings without ranking them -- claims nothing.
    """
    found: list[Block] = []
    for sibling in reversed(list(siblings[:position])):
        if sibling.kind is not BlockKind.HEADING:
            continue
        if floor is not None and sibling.level >= floor:
            continue
        found.append(sibling)
        floor = sibling.level
    return tuple(found)


# --- the profile, compiled once per call ------------------------------------


@dataclass(frozen=True, slots=True)
class _Rule:
    """One `redlines.profiles.RoleRule` with its list position and pattern."""

    index: int
    rule: RoleRule
    pattern: re.Pattern[str] | None


@dataclass(frozen=True, slots=True)
class _Extractor:
    """One `redlines.profiles.SpanExtractor` with its pattern compiled."""

    type: str
    group: int
    pattern: re.Pattern[str]


@dataclass(frozen=True, slots=True)
class _Semantics:
    """Everything one `apply_semantics` call needs, compiled once.

    :param rules: the profile's role rules, in order, patterns compiled.
    :param extractors: the profile's span extractors, in order.
    :param definitions: whether the PRD § 6b definitions heuristic runs, which
        is whether the profile names the `definitions` or `definition` role.
    :param definitions_order: the list position the heuristic's `definitions`
        claims take -- that of the first profile rule naming the role, or the
        position after the last rule where none does.
    :param definition_order: the same for its `definition` claims.
    """

    rules: tuple[_Rule, ...]
    extractors: tuple[_Extractor, ...]
    definitions: bool
    definitions_order: int
    definition_order: int


def _compile(profile: Profile) -> _Semantics:
    """Compile ``profile``'s role rules and span extractors for one pass.

    :raises ValueError: if a span extractor names a capturing group its pattern
        does not have. `redlines.profiles.load_profile` rejects that, so this
        can only be reached by a `Profile` built by hand.
    """
    rules = tuple(
        _Rule(
            index=index,
            rule=rule,
            pattern=rule.compiled() if rule.pattern is not None else None,
        )
        for index, rule in enumerate(profile.role_rules)
    )
    extractors = []
    for extractor in profile.span_extractors:
        pattern = extractor.compiled()
        if extractor.group > pattern.groups:
            raise ValueError(
                f"span extractor {extractor.type!r} wants group "
                f"{extractor.group}, but its pattern has {pattern.groups}"
            )
        extractors.append(
            _Extractor(type=extractor.type, group=extractor.group, pattern=pattern)
        )
    definitions = any(
        rule.role in (DEFINITIONS_ROLE, DEFINITION_ROLE) for rule in profile.role_rules
    )
    return _Semantics(
        rules=rules,
        extractors=tuple(extractors),
        definitions=definitions,
        definitions_order=_first_naming(profile.role_rules, DEFINITIONS_ROLE),
        definition_order=_first_naming(profile.role_rules, DEFINITION_ROLE),
    )


def _first_naming(rules: Sequence[RoleRule], role: str) -> int:
    """Return the position of the first rule assigning ``role``, or ``len(rules)``."""
    for index, rule in enumerate(rules):
        if rule.role == role:
            return index
    return len(rules)


# --- roles ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Match:
    """One claim on a block's role.

    Claims from the profile are settled by ``order`` -- the schema's "the first
    rule that matches wins" -- except among ``ancestor_heading`` claims, which
    are settled by ``distance`` first (ADR-0028's one exception). The pass's
    own definitions rule, which is in no profile, is ordered as if it were the
    profile rule that names the role it assigns, so it competes by ``order``
    like everything else.

    :param distance: how far away the evidence is -- 0 for the block itself,
        1 for its parent or the nearest heading it sits under, 2 for the
        heading outside that, and so on. Recorded for every claim; decisive
        only among ``ancestor_heading`` claims.
    :param order: the claimant's position in the profile's ``role_rules``. The
        definitions rule takes the position of the first rule naming
        `definitions` or `definition`, as the claim requires, and the position
        after the last rule where the profile names neither; a profile rule
        wins a tie with it.
    :param role: the role claimed.
    :param kind: what to record in ``attrs["semantic"]`` as ``role_match``.
    :param rule: the profile rule's index, or ``None`` for the definitions rule.
    :param detail: the evidence, as ordered key/value pairs.
    """

    distance: int
    order: int
    role: str
    kind: str
    rule: int | None
    detail: tuple[tuple[str, Any], ...] = ()


def _heading_match(pattern: re.Pattern[str], heading: Block) -> str | None:
    """Return which spelling of ``heading`` ``pattern`` matched, or ``None``.

    The heading's own ``text`` first -- the label is already off it -- and then
    the heading as written, label and text rejoined, which is the only way to
    reach a heading whose label is the whole of it (``SCHEDULE 1``).
    """
    if heading.text and pattern.search(heading.text) is not None:
        return "text"
    line = heading_line(heading)
    if line and line != heading.text and pattern.search(line) is not None:
        return "heading_line"
    return None


def _role_match(
    block: Block,
    *,
    parent_role: str | None,
    ancestors: Sequence[Block],
    rules: Sequence[_Rule],
) -> _Match | None:
    """Return the winning role rule for ``block``: list order, ancestors first.

    ADR-0028 and the schema's ``role_rules`` description together: rules are
    tried in order and the first match wins, and the single exception is that
    ``ancestor_heading`` rules resolve from the block outwards, where the
    nearest matching ancestor decides and list order only breaks a tie between
    rules matching that same heading. So the ancestor claims are settled among
    themselves first and the losers drop out; the earliest-listed of what
    survives is the block's role.
    """
    claims = [
        found
        for found in (
            _match_one(entry, block, parent_role=parent_role, ancestors=ancestors)
            for entry in rules
        )
        if found is not None
    ]
    nearest = min(
        (claim for claim in claims if claim.kind == _MATCH_ANCESTOR),
        key=lambda claim: (claim.distance, claim.order),
        default=None,
    )
    surviving = [
        claim for claim in claims if claim.kind != _MATCH_ANCESTOR or claim is nearest
    ]
    if not surviving:
        return None
    return min(surviving, key=lambda claim: claim.order)


def _match_one(
    entry: _Rule,
    block: Block,
    *,
    parent_role: str | None,
    ancestors: Sequence[Block],
) -> _Match | None:
    """Return ``entry``'s claim on ``block``, at the distance it applies from."""
    rule = entry.rule
    if rule.kind is not None and block.kind.value != rule.kind:
        return None
    filtered: tuple[tuple[str, Any], ...] = (
        (("kind", block.kind.value),) if rule.kind is not None else ()
    )
    if rule.match == _MATCH_TEXT:
        # The block's own evidence, so distance 0: nothing is closer.
        if entry.pattern is None or not block.text:
            return None
        found = entry.pattern.search(block.text)
        if found is None:
            return None
        return _Match(
            0,
            entry.index,
            rule.role,
            rule.match,
            entry.index,
            (("matched", found.group(0)),) + filtered,
        )
    if rule.match == _MATCH_LABEL:
        if entry.pattern is None or not block.label:
            return None
        if entry.pattern.search(block.label) is None:
            return None
        return _Match(
            0,
            entry.index,
            rule.role,
            rule.match,
            entry.index,
            (("label", block.label),) + filtered,
        )
    if rule.match == _MATCH_HEADING:
        if block.kind is not BlockKind.HEADING or entry.pattern is None:
            return None
        matched = _heading_match(entry.pattern, block)
        if matched is None:
            return None
        return _Match(
            0, entry.index, rule.role, rule.match, entry.index, (("matched", matched),)
        )
    if rule.match == _MATCH_PARENT_ROLE:
        if parent_role is None or parent_role != rule.parent_role:
            return None
        return _Match(
            1,
            entry.index,
            rule.role,
            rule.match,
            entry.index,
            (("parent_role", parent_role),) + filtered,
        )
    if rule.match == _MATCH_ANCESTOR:
        if entry.pattern is None:
            return None
        for distance, ancestor in enumerate(ancestors, start=1):
            if _heading_match(entry.pattern, ancestor) is not None:
                return _Match(
                    distance,
                    entry.index,
                    rule.role,
                    rule.match,
                    entry.index,
                    (("ancestor", heading_line(ancestor)),) + filtered,
                )
    # An unknown match kind is not reachable through the loader, whose enum is
    # closed; a hand-built rule that invents one simply never matches.
    return None


# --- definitions (PRD § 6b) -------------------------------------------------


def _definitions_heading(heading: Block, rules: Sequence[_Rule]) -> bool:
    """Whether the profile's own heading rules call ``heading`` a definitions one.

    Heading rules are the closest evidence there is (distance 0), so the first
    one that matches is the one that would decide the heading's role; this asks
    whether that one assigns `DEFINITIONS_ROLE`.
    """
    for entry in rules:
        if entry.rule.match != _MATCH_HEADING or entry.pattern is None:
            continue
        if _heading_match(entry.pattern, heading) is not None:
            return entry.rule.role == DEFINITIONS_ROLE
    return False


def _body_end(children: Sequence[Block], position: int) -> int:
    """Return where the heading at ``position`` stops holding its siblings.

    At the next heading of the same or a lower level -- a deeper heading is
    still under this one -- or at the end of the list.
    """
    level = children[position].level
    for index in range(position + 1, len(children)):
        child = children[index]
        if child.kind is BlockKind.HEADING and child.level <= level:
            return index
    return len(children)


def _shape_hits(text: str) -> tuple[tuple[int, int], ...]:
    """Return the range of every *quoted term, "means"* term in ``text``."""
    return tuple(match.span(1) for match in _DEFINITION_SHAPE.finditer(text))


def _definitions_path(
    heading: Block, body: Sequence[Block], rules: Sequence[_Rule]
) -> str | None:
    """Return which of PRD § 6b's two definitions paths fires, if either.

    :return: ``"heading"`` when the profile's own rule recognises the heading,
        ``"shape"`` when the members read like definitions, else ``None``.
    """
    if _definitions_heading(heading, rules):
        return "heading"
    members = [child for child in body if child.kind in DEFINITION_MEMBER_KINDS]
    if not members:
        return None
    hits = [len(_shape_hits(member.text)) for member in members]
    if len(members) == 1:
        # One block holding two or more definitions is the run-on paragraph
        # PRD § 6b names as a hard case, not a clause that quotes something.
        return "shape" if hits[0] >= 2 else None
    matching = sum(1 for count in hits if count)
    return "shape" if matching * 2 > len(members) else None


def _definitions_plan(
    children: Sequence[Block], rules: Sequence[_Rule]
) -> dict[int, tuple[str, str]]:
    """Map each position the definitions rule claims to ``(role, path)``.

    The heading takes `DEFINITIONS_ROLE`, its text-block members take
    `DEFINITION_ROLE`. Headings are walked in order, so where bodies nest the
    *nearest* heading is the last to write and therefore the one that decides.
    """
    plan: dict[int, tuple[str, str]] = {}
    for position, child in enumerate(children):
        if child.kind is not BlockKind.HEADING:
            continue
        end = _body_end(children, position)
        path = _definitions_path(child, children[position + 1 : end], rules)
        if path is None:
            continue
        plan[position] = (DEFINITIONS_ROLE, path)
        for index in range(position + 1, end):
            if children[index].kind in DEFINITION_MEMBER_KINDS:
                plan[index] = (DEFINITION_ROLE, path)
    return plan


def _definitions_container(section: Block, rules: Sequence[_Rule]) -> str | None:
    """Return the path that makes ``section`` a definitions section, if any.

    "A section whose first child is the heading" -- the shape both built-in
    readers build. On a flat tree there is no such block, and the heading and
    its members carry the roles on their own.
    """
    if section.kind is not BlockKind.SECTION or not section.children:
        return None
    heading = section.children[0]
    if heading.kind is not BlockKind.HEADING:
        return None
    end = _body_end(section.children, 0)
    return _definitions_path(heading, section.children[1:end], rules)


# --- spans ------------------------------------------------------------------


def _reference_value(text: str) -> str:
    """Normalise a captured cross-reference the way a reader normalises a label.

    Whitespace collapsed to single spaces, ends stripped, one trailing full
    stop dropped -- so ``"clause 7.2."`` refers to ``"7.2"`` and ``"Schedule
    2"`` to itself.
    """
    value = _WHITESPACE.sub(" ", text).strip()
    return value[:-1] if value.endswith(".") else value


def _spans_from(text: str, extractors: Sequence[_Extractor]) -> list[Span]:
    """Run every extractor over ``text`` and return the spans, in extractor order."""
    found: list[Span] = []
    for extractor in extractors:
        for match in extractor.pattern.finditer(text):
            if match.group(extractor.group) is None:
                continue
            start, end = match.span(extractor.group)
            if start < 0 or end <= start:
                # A group that matched nothing is not a range of text.
                continue
            value = (
                _reference_value(text[start:end])
                if extractor.type == CROSS_REFERENCE_TYPE
                else None
            )
            found.append(Span(type=extractor.type, start=start, end=end, value=value))
    return found


def extract_spans(text: str, *, profile: Profile) -> tuple[Span, ...]:
    """Return the spans ``profile``'s extractors find in ``text``.

    The span half of the pass on its own, for a caller that has text rather
    than a tree. Offsets are into ``text``; see this module's docstring for
    what happens when two extractors overlap.

    :param text: one block's text.
    :param profile: the active profile.
    :return: the spans, in extractor order, at most one of each type per range.
    """
    semantics = _compile(profile)
    return _dedupe(_spans_from(text, semantics.extractors))


def _dedupe(
    spans: Sequence[Span], *, seen: frozenset[tuple[str, int, int]] = frozenset()
) -> tuple[Span, ...]:
    """Keep the first span of each ``(type, start, end)``, in the order given."""
    taken: set[tuple[str, int, int]] = set(seen)
    kept: list[Span] = []
    for span in spans:
        key = (span.type, span.start, span.end)
        if key in taken:
            continue
        taken.add(key)
        kept.append(span)
    return tuple(kept)


def _merge_spans(existing: Sequence[Span], found: Sequence[Span]) -> tuple[Span, ...]:
    """Return ``existing`` followed by the spans of ``found`` it does not already carry.

    Keeping what is already there first is what makes a second pass a no-op and
    what protects a span a reader emitted from the format itself (ADR-0024).
    """
    taken = frozenset((span.type, span.start, span.end) for span in existing)
    return tuple(existing) + _dedupe(found, seen=taken)


# --- the pass ---------------------------------------------------------------


def apply_semantics(tree: BlockTree, profile: Profile) -> BlockTree:
    """Assign roles and spans over ``tree`` under ``profile`` (R1b, PRD § 6b).

    Pure and deterministic: ``tree`` is not touched, the result is a new tree
    with the same shape, addresses and ``dropped`` report, and applying the
    pass to its own output changes nothing (N1). A profile with no
    ``role_rules`` and no ``span_extractors`` returns the tree unchanged.

    :param tree: a tree from a reader, or any tree of the same shape.
    :param profile: the structure profile whose ``role_rules`` and
        ``span_extractors`` drive the pass (ADR-0006).
    :return: a new `redlines.blocks.BlockTree` whose blocks carry roles, spans
        and, where the pass decided something, an ``attrs["semantic"]`` record
        of what it decided and why.
    :raises ValueError: if a span extractor names a capturing group its pattern
        does not have, or a span lands outside its block's text.
    """
    semantics = _compile(profile)
    root = _visit(
        tree.root,
        parent_role=None,
        ancestors=(),
        planned=None,
        semantics=semantics,
    )
    return BlockTree.build(root, dropped=tree.dropped)


def _visit(
    block: Block,
    *,
    parent_role: str | None,
    ancestors: tuple[Block, ...],
    planned: tuple[str, str] | None,
    semantics: _Semantics,
) -> Block:
    """Return ``block`` with its role, spans and children resolved.

    Top-down: the block's own role is settled before its children are walked,
    so a ``parent_role`` rule and the definitions rule both see a decided
    parent.
    """
    note: dict[str, Any] = {}
    role = block.role

    claims = [
        claim
        for claim in (
            _role_match(
                block,
                parent_role=parent_role,
                ancestors=ancestors,
                rules=semantics.rules,
            ),
            _definitions_match(block, planned=planned, semantics=semantics),
        )
        if claim is not None
    ]
    if claims:
        # The profile has already settled its own rules by list order, and the
        # definitions rule stands at the position of the profile rule that
        # names its role, so this is list order too. The profile's claim is
        # first in the list, so it wins a tie.
        match = min(claims, key=lambda claim: claim.order)
        role = match.role
        note.update(
            {
                "role": match.role,
                "role_match": match.kind,
                "role_rule": match.rule,
                **dict(match.detail),
            }
        )

    spans = _merge_spans(block.spans, _spans_from(block.text, semantics.extractors))
    if role == DEFINITION_ROLE and semantics.definitions:
        hits = _shape_hits(block.text)
        if hits:
            note["defined_terms"] = len(hits)
            spans = _merge_spans(
                spans,
                [
                    Span(type=DEFINED_TERM_TYPE, start=start, end=end)
                    for start, end in hits
                ],
            )
    if spans and (semantics.extractors or semantics.definitions):
        # The count the block ends the pass with, not the number added, so
        # that a second pass -- which adds nothing -- writes the same record.
        note["spans"] = len(spans)

    # Every heading outside this block, one step further away for a child of
    # it, preceded by this block itself where it is a heading holding its own
    # content. Nearest first, so position is distance.
    outer = ancestors
    if block.kind is BlockKind.HEADING:
        outer = (block,) + outer
    plan = (
        _definitions_plan(block.children, semantics.rules)
        if semantics.definitions
        else {}
    )
    children = tuple(
        _visit(
            child,
            parent_role=role,
            ancestors=_preceding_headings(
                block.children,
                position,
                floor=child.level if child.kind is BlockKind.HEADING else None,
            )
            + outer,
            planned=plan.get(position),
            semantics=semantics,
        )
        for position, child in enumerate(block.children)
    )

    attrs: Mapping[str, Any] = block.attrs
    if note:
        attrs = {**block.attrs, "semantic": note}
    return replace(block, role=role, spans=spans, attrs=attrs, children=children)


def _definitions_match(
    block: Block, *, planned: tuple[str, str] | None, semantics: _Semantics
) -> _Match | None:
    """Return PRD § 6b's definitions rule's claim on ``block``, if it has one.

    The rule is written here because the profile format cannot say it, so it
    competes on the format's own terms: it records the distance of the
    evidence it used -- the block's own heading, or the heading beside it --
    and takes the list position of the profile rule that names the role it is
    assigning, so that "``clause`` listed after ``definition``" means the same
    on a tree with no section block to carry a ``parent_role`` as on one with
    it. A profile rule that ties with it wins.

    :param planned: ``(role, path)`` from `_definitions_plan`, set by the
        block's parent where the block is a definitions heading or one of its
        members; ``None`` for every other block, which is then only tested for
        being a definitions *section*.
    """
    if not semantics.definitions:
        return None
    if planned is not None:
        role, path = planned
        # A heading is its own evidence; a member is told by the heading beside
        # it, one step away, like a `parent_role` or a nearest ancestor.
        if role == DEFINITIONS_ROLE:
            return _Match(0, semantics.definitions_order, role, f"{role}_{path}", None)
        return _Match(1, semantics.definition_order, role, f"{role}_{path}", None)
    opened = _definitions_container(block, semantics.rules)
    if opened is None:
        return None
    return _Match(
        0,
        semantics.definitions_order,
        DEFINITIONS_ROLE,
        f"{DEFINITIONS_ROLE}_{opened}",
        None,
    )
