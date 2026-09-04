"""Structure profiles: the declarative format that drives readers (ADR-0006, ADR-0028).

Most projects never import this module directly. The normal path is
``Redlines(a, b, profile="contract")`` (or ``--profile contract`` on the
CLI) picking one of the built-in profiles by name (``generic``, ``contract``,
``markdown``) or, later, letting auto-selection choose. This module is what a
reader calls internally to turn that name -- or a file, or a mapping -- into a
validated `Profile`.

Three profiles ship in core (#101), listed in `BUILTIN_PROFILE_NAMES` and
loaded by `builtin_profile`; each is a commented YAML file under
``redlines/profiles/builtin/`` that anyone can read or copy. Pick by what
the document is, not by how it was typed. ``contract`` is for numbered
commercial agreements in plain text -- decimal clauses, ``(a)``/``(ii)``
sub-clauses, ``Article 5``/``Schedule 2`` word labels, schedules that
restart numbering, and definition, recital, schedule and signature roles
with defined-term, cross-reference, party, date and amount spans -- and is
what a ``.txt`` contract gets by default. ``markdown`` is the same document
family seen through markdown syntax: headings, lists and tables come from
the ``#``s and markers, so the profile describes only what is left in the
stripped text, and it is the default for ``.md``. ``generic`` declares no
labels, no numbering resets and no roles at all, so a reader degrades to one
block per paragraph with alignment still working; choose it for an unknown
family, and start from it when writing your own. ``legislation`` and
automatic selection are 1.1 (PRD R1d); until then, name the profile you want.

Writing a profile is the escape hatch for a document family none of the
built-ins fit well, not something every project is expected to do. When
that's needed, a profile can be handed over three ways, none of which
requires a file on disk:

```python
from redlines.profiles import load_profile

profile = load_profile({"name": "my_family", "label_patterns": [...]})  # a plain dict
profile = load_profile('name: my_family')                                # raw YAML text
profile = load_profile("my_profile.yaml")                                # a file, if you have one
```

Order means different things in the three rule lists, because a block can
carry one label and one role but many spans:

- ``label_patterns`` -- tried in order, **first match wins**.
- ``role_rules`` -- tried in order, **first match wins**; a block has one role.
  Where two ``ancestor_heading`` rules both match, the nearest ancestor
  heading decides and order only breaks the tie between rules matching it.
- ``span_extractors`` -- **every** extractor runs and all matches are kept;
  order only fixes the order the spans come out in.

A profile is trusted input. Its patterns are regular expressions someone
else's document text will be run against, and a valid pattern can take
exponential time to match, so treat authoring a profile as equivalent to
running code -- the same standing a Vale or Semgrep rule file has. See
`load_profile` for what that means for a paste box or an MCP argument.

See ``docs/adr/0028-profile-file-format.md`` for the format's design rationale
and ``redlines/profiles/schema.json`` for the published JSON Schema -- the
schema and one worked example (``tests/profiles/example_contract.yaml``) are
meant to be enough for a model to draft a custom profile in one turn (R1f).
"""

from __future__ import annotations

from importlib.resources import files

from .builtin import BUILTIN_PROFILE_NAMES, builtin_profile
from .errors import ProfileError
from .model import (
    HeadingReset,
    HeadingRule,
    LabelPattern,
    Profile,
    RoleRule,
    SpanExtractor,
)
from .loader import load_profile, parse_profile_yaml, profile_from_mapping


def profile_schema_text() -> str:
    """Return the published JSON Schema for the profile format, as text.

    Read from the installed package rather than the source tree, so the
    separate MCP server package (ADR-0017) can serve it as a resource
    (ADR-0018) without reaching into redlines' own directory layout.
    """
    return (files(__package__) / "schema.json").read_text(encoding="utf-8")


__all__ = [
    "BUILTIN_PROFILE_NAMES",
    "HeadingReset",
    "HeadingRule",
    "LabelPattern",
    "Profile",
    "ProfileError",
    "RoleRule",
    "SpanExtractor",
    "builtin_profile",
    "load_profile",
    "parse_profile_yaml",
    "profile_from_mapping",
    "profile_schema_text",
]
