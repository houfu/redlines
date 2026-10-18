"""Scoping a change tree down to the changes a caller actually wants (#138).

`redlines.changes.build_change_tree` reports everything that happened.
`ChangeFilter` is a declarative, serialisable statement of *which subset* of
that a caller wants -- a CLI flag set, an MCP tool argument, and (in 1.1)
`verify`'s ``allowed`` scope, all as one type (ADR-0025, ADR-0033). A bag of
keyword arguments would have to be re-parsed in each of those places; a value
with `to_dict`/`from_dict` travels between them unchanged.

**Semantics.** An empty field is no constraint. Fields AND together. Values
within one field OR: ``kinds=("insert", "delete")`` means "an insert or a
delete", and adding ``roles=("clause",)`` on top narrows to "an insert or a
delete that is also a clause". This is the only reading a future ``verify``
can live with -- a scope built from several dimensions has to narrow, never
widen, as each one is added.

**Address prefixes are segment-aligned.** A prefix matches an address when
the address equals the prefix or starts with the prefix plus a slash --
never a bare `str.startswith`, which would let ``/section[1]`` match
``/section[11]``. Both exist in the sample pair (`tests/corpus/sample_pair`),
so this is a real bug a naive implementation would ship. `ROOT_PATH`
(``"/"``) matches every address. A prefix is tested against **either**
address on the change, so a scope naming a clause's old location still
reports it after it moved somewhere else.

**`min_chars` is in changed characters**, compared against
``max(change.chars_added, change.chars_deleted)`` -- the same accessors
`redlines.statistics` sums, so the filter and the statistics can never
disagree about what a "20-character edit" is (ADR-0033). Those accessors are
computed from a node's inline ops, and an `insert` or a `delete` never carries
any (the whole block is the change): the practical consequence is that
``min_chars > 0`` excludes every insert and delete, however large the block,
along with every renumber -- it is a filter for "show me the substantive
*edits*", not "show me the substantial changes". A caller wanting inserted or
deleted blocks kept regardless of size combines ``min_chars`` with
``kinds=("modify",)`` rather than leaving ``kinds`` open.

**`has_inline`** exists because kind precedence is ``move > renumber >
modify``: a clause that was both renumbered and edited is a ``renumber``
node, so filtering strictly on ``kind == "modify"`` would silently miss its
edit. ``has_inline=True`` is "show me anything with a text edit, whatever its
kind"; ``has_inline=False`` is its complement, and ``None`` (the default) is
no constraint at all.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from .blocks import ROOT_PATH, _reject_unknown_keys
from .changes import Change, ChangeKind, ChangeTree

__all__: tuple[str, ...] = ("ChangeFilter", "filter_changes")

_FILTER_KEYS: Final[set[str]] = {
    "kinds",
    "address_prefixes",
    "labels",
    "roles",
    "min_chars",
    "has_inline",
}


@dataclass(frozen=True, slots=True)
class ChangeFilter:
    """A declarative scope over a `ChangeTree` (#138, ADR-0033).

    :param kinds: keep only these `redlines.changes.ChangeKind` values.
        ``()`` (the default) is no constraint.
    :param address_prefixes: keep only a change whose ``source_address`` or
        ``test_address`` sits at or under one of these addresses,
        segment-aligned. ``()`` is no constraint.
    :param labels: keep only a change whose ``source_label`` or ``test_label``
        is one of these. ``()`` is no constraint.
    :param roles: keep only a change whose `redlines.changes.Change.role` is
        one of these. ``()`` is no constraint.
    :param min_chars: keep only a change whose
        ``max(chars_added, chars_deleted)`` is at least this many characters.
        ``0`` (the default) is no constraint. In changed characters, not
        tokens, because v1's ``Stats`` already counts characters and "at
        least 20 characters" is a threshold a person can picture.
    :param has_inline: ``True`` keeps only a change with at least one inline
        op, ``False`` keeps only one with none, ``None`` (the default) is no
        constraint.
    """

    kinds: tuple[ChangeKind, ...] = ()
    address_prefixes: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    min_chars: int = 0
    has_inline: bool | None = None

    def __post_init__(self) -> None:
        """Coerce ``kinds`` and freeze every sequence field."""
        object.__setattr__(self, "kinds", tuple(ChangeKind(kind) for kind in self.kinds))
        object.__setattr__(
            self, "address_prefixes", tuple(str(p) for p in self.address_prefixes)
        )
        object.__setattr__(self, "labels", tuple(str(label) for label in self.labels))
        object.__setattr__(self, "roles", tuple(str(role) for role in self.roles))
        if self.min_chars < 0:
            raise ValueError(f"min_chars must not be negative, got {self.min_chars}")

    def matches(self, change: Change) -> bool:
        """Whether ``change`` falls inside this scope.

        :param change: the node to test.
        :return: ``True`` when every non-empty field's constraint is met.
        """
        if self.kinds and change.kind not in self.kinds:
            return False
        if self.address_prefixes and not any(
            _address_matches(change, prefix) for prefix in self.address_prefixes
        ):
            return False
        if self.labels and not (
            change.source_label in self.labels or change.test_label in self.labels
        ):
            return False
        if self.roles and change.role not in self.roles:
            return False
        if self.min_chars and max(change.chars_added, change.chars_deleted) < self.min_chars:
            return False
        if self.has_inline is not None and change.has_inline != self.has_inline:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        """Return the filter as a JSON-serialisable dict, in a fixed key order.

        :return: a dict with the keys ``kinds``, ``address_prefixes``,
            ``labels``, ``roles``, ``min_chars`` and ``has_inline``.
        """
        return {
            "kinds": [kind.value for kind in self.kinds],
            "address_prefixes": list(self.address_prefixes),
            "labels": list(self.labels),
            "roles": list(self.roles),
            "min_chars": self.min_chars,
            "has_inline": self.has_inline,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ChangeFilter:
        """Rebuild a filter from `to_dict` output.

        :param data: a mapping in the shape `to_dict` produces.
        :return: the reconstructed `ChangeFilter`.
        :raises ValueError: if a key is unknown, a kind is outside the closed
            set, or ``min_chars`` is negative.
        """
        _reject_unknown_keys(data, _FILTER_KEYS, "change filter")
        has_inline = data.get("has_inline")
        return cls(
            kinds=tuple(ChangeKind(kind) for kind in data.get("kinds", ()) or ()),
            address_prefixes=tuple(
                str(p) for p in data.get("address_prefixes", ()) or ()
            ),
            labels=tuple(str(label) for label in data.get("labels", ()) or ()),
            roles=tuple(str(role) for role in data.get("roles", ()) or ()),
            min_chars=int(data.get("min_chars", 0)),
            has_inline=None if has_inline is None else bool(has_inline),
        )


def filter_changes(tree: ChangeTree, spec: ChangeFilter) -> ChangeTree:
    """Return a `ChangeTree` holding only the nodes ``spec`` matches.

    :param tree: the tree to scope down.
    :param spec: the scope.
    :return: a new tree, the same document order preserved, holding exactly
        the nodes for which ``spec.matches(node)`` is ``True``.
    """
    return ChangeTree(changes=tuple(change for change in tree if spec.matches(change)))


def _address_matches(change: Change, prefix: str) -> bool:
    """Whether ``prefix`` matches either address on ``change``, segment-aligned."""
    return _prefix_matches(change.source_address, prefix) or _prefix_matches(
        change.test_address, prefix
    )


def _prefix_matches(address: str | None, prefix: str) -> bool:
    """Whether ``address`` equals ``prefix`` or sits under it, segment-aligned.

    A plain ``str.startswith`` would let ``/section[1]`` match
    ``/section[11]``; `ROOT_PATH` matches every address.
    """
    if address is None:
        return False
    if prefix == ROOT_PATH:
        return True
    return address == prefix or address.startswith(prefix.rstrip("/") + "/")
