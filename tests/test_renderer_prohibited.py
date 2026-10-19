"""What a renderer must not contain, found by reading its source (N1, ADR-0037, #184).

ADR-0037 ("Where the code lives, and determinism") makes a renderer's output a
function of the comparison alone. In ``redlines/renderers/`` it prohibits
iterating a ``set`` for output, timestamps, random or ``id()``-based ids and
locale formatting. ``tests/test_render_determinism.py`` shows what a construct
of that kind *did* on the documents it renders, under five hash seeds; this
module reads the constructs themselves, so one that misbehaves only on a
document nobody has tried fails here too.

The scan reads syntax, not types, and fails on three rules:

- ``import``: an import of ``time``, ``datetime``, ``random``, ``uuid``,
  ``secrets`` or ``locale`` however it is spelled or aliased, or a
  ``__import__`` or ``import_module`` call that names one;
- ``call``: a call to the builtin ``id`` or ``hash``, whose results differ
  from one run to the next (``hash`` of a string follows the hash seed);
- ``set-iteration``: iterating a set, or writing one out. A set is a set
  display or comprehension, a ``set()`` or ``frozenset()`` call, a set
  operator or method applied to one, or a name bound to one in its own scope
  or the module (by assignment, or by a ``set[...]`` or ``frozenset[...]``
  annotation). Iterating one means a ``for`` loop, a list, dict or generator
  comprehension, unpacking, ``list()``, ``tuple()``, ``enumerate()``,
  ``zip()``, ``map()``, ``filter()``, ``iter()``, ``reversed()``, ``str()``,
  ``repr()``, ``.join()``, ``dict.fromkeys()`` and an f-string field.

Testing membership (``kind in KINDS``), sizing a set, building a set from a
set and ordering one (``sorted(KINDS)``, or a generator over it handed to
``sorted()``, ``set()``, ``frozenset()``, ``any()`` or ``all()``) are not
iterations for output and pass.

What it cannot see, the hash-seed test still can: a set held in an attribute,
returned by a function or made by a call the scan does not know.

**Allowing a construct.** A comment on the line, or on the line above it,
``# determinism: allow RULE -- REASON``, lets that rule through there. The
reason is required, and a comment that is malformed, names an unknown rule or
allows nothing is itself a finding, so an allowance cannot outlive its
construct. No renderer uses one.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
RENDERERS = REPO_ROOT / "redlines" / "renderers"
MODULES = sorted(RENDERERS.glob("*.py"))

PROHIBITED_MODULES: Final[tuple[str, ...]] = (
    "time",
    "datetime",
    "random",
    "uuid",
    "secrets",
    "locale",
)
PROHIBITED_CALLS: Final[tuple[str, ...]] = ("id", "hash")

IMPORT: Final = "import"
CALL: Final = "call"
SET_ITERATION: Final = "set-iteration"
ALLOW: Final = "allow"
"""The rule of a finding about an allow comment, which no comment can allow."""
RULES: Final = (IMPORT, CALL, SET_ITERATION)

_SET_CONSTRUCTORS: Final = ("set", "frozenset")
_SET_METHODS: Final = (
    "union",
    "intersection",
    "difference",
    "symmetric_difference",
    "copy",
)
_SET_OPERATORS: Final = (ast.BitOr, ast.BitAnd, ast.Sub, ast.BitXor)
_SET_TYPES: Final = (
    "set",
    "frozenset",
    "Set",
    "FrozenSet",
    "AbstractSet",
    "MutableSet",
)
_WRAPPING_TYPES: Final = ("Final", "ClassVar", "Annotated", "Optional")
_ORDERED_CONSUMERS: Final = (
    "list",
    "tuple",
    "iter",
    "enumerate",
    "reversed",
    "zip",
    "map",
    "filter",
    "str",
    "repr",
)
_ORDERED_METHODS: Final = ("join", "fromkeys")
_ORDER_FREE_CONSUMERS: Final = ("sorted", "set", "frozenset", "any", "all")
_FUNCTIONS: Final = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
_SCOPES: Final = (*_FUNCTIONS, ast.ClassDef)


@dataclass(frozen=True)
class Finding:
    """One construct the scan rejects: the line it is on, the rule, and why."""

    line: int
    rule: str
    message: str


# -- allow comments ----------------------------------------------------------------------

_MARKER = re.compile(r"#\s*determinism:\s*allow\b")
_ALLOW = re.compile(
    r"#\s*determinism:\s*allow\s+(?P<rules>[a-z-]+(?:,[a-z-]+)*)\s+--\s+(?P<reason>\S.*)$"
)


def _allowances(source: str) -> tuple[dict[tuple[int, str], int], list[Finding]]:
    """The allow comments of ``source``.

    A comment after code allows its own line, and one on a line of its own
    allows the next.

    :param source: a Python module's text.
    :return: the allowed ``(line, rule)`` pairs, each with the line of the
        comment that allows it, and a finding for every malformed comment.
    """
    allowed: dict[tuple[int, str], int] = {}
    malformed: list[Finding] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT or not _MARKER.match(token.string):
            continue
        line = token.start[0]
        match = _ALLOW.match(token.string)
        rules = match["rules"].split(",") if match else []
        if match is None or any(rule not in RULES for rule in rules):
            malformed.append(
                Finding(
                    line,
                    ALLOW,
                    "an allow comment reads '# determinism: allow RULE -- REASON', "
                    f"RULE being one of {', '.join(RULES)}",
                )
            )
            continue
        alone = token.line[: token.start[1]].strip() == ""
        for rule in rules:
            allowed[(line + 1 if alone else line, rule)] = line
    return allowed, malformed


# -- scopes and sets ---------------------------------------------------------------------


@dataclass
class _Scope:
    """The names one scope binds, and which of them hold a set."""

    is_class: bool = False
    bound: set[str] = field(default_factory=set)
    sets: set[str] = field(default_factory=set)


def _tail(node: ast.expr) -> str | None:
    """The last name of ``node``: ``set`` for ``set`` and for ``builtins.set`` alike."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _is_set_annotation(node: ast.expr) -> bool:
    """Whether an annotation names a set type, as in ``Final[frozenset[str]]``."""
    if isinstance(node, ast.Subscript):
        head = _tail(node.value)
        if head in _SET_TYPES:
            return True
        if head in _WRAPPING_TYPES:
            inner = node.slice
            if isinstance(inner, ast.Tuple) and inner.elts:
                inner = inner.elts[0]
            return _is_set_annotation(inner)
        return False
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _is_set_annotation(node.left) or _is_set_annotation(node.right)
    return _tail(node) in _SET_TYPES


def _name_is_set(name: str, scopes: Sequence[_Scope]) -> bool:
    """Whether ``name`` holds a set where the innermost scope binds it.

    A class body is not visible from the functions inside it, so only the
    innermost scope may be one.
    """
    for depth, scope in enumerate(reversed(scopes)):
        if scope.is_class and depth > 0:
            continue
        if name in scope.bound:
            return name in scope.sets
    return False


def _is_set(node: ast.expr, scopes: Sequence[_Scope]) -> bool:
    """Whether ``node`` is a set on its face; see the module docstring."""
    if isinstance(node, (ast.Set, ast.SetComp)):
        return True
    if isinstance(node, ast.Call):
        function = node.func
        if isinstance(function, ast.Name):
            return function.id in _SET_CONSTRUCTORS
        return (
            isinstance(function, ast.Attribute)
            and function.attr in _SET_METHODS
            and _is_set(function.value, scopes)
        )
    if isinstance(node, ast.BinOp):
        return isinstance(node.op, _SET_OPERATORS) and (
            _is_set(node.left, scopes) or _is_set(node.right, scopes)
        )
    if isinstance(node, ast.Name):
        return _name_is_set(node.id, scopes)
    return False


def _own_nodes(node: ast.AST) -> Iterator[ast.AST]:
    """The nodes of one scope in source order, a nested scope's node but not its body."""
    for child in ast.iter_child_nodes(node):
        yield child
        if not isinstance(child, _SCOPES):
            yield from _own_nodes(child)


def _scope_of(node: ast.AST, enclosing: Sequence[_Scope]) -> _Scope:
    """What the module, function or class ``node`` binds, found before any use is read.

    Flow does not matter: a name that is bound to a set anywhere in its scope
    is a set everywhere in it.
    """
    scope = _Scope(is_class=isinstance(node, ast.ClassDef))
    scopes = [*enclosing, scope]
    if isinstance(node, _FUNCTIONS):
        arguments = node.args
        for argument in (
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
            arguments.vararg,
            arguments.kwarg,
        ):
            if argument is None:
                continue
            scope.bound.add(argument.arg)
            if argument.annotation is not None and _is_set_annotation(
                argument.annotation
            ):
                scope.sets.add(argument.arg)
    for child in _own_nodes(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
            scope.bound.add(child.id)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            scope.bound.add(child.name)
        elif isinstance(child, (ast.Import, ast.ImportFrom)):
            for alias in child.names:
                scope.bound.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(child, ast.Assign) and _is_set(child.value, scopes):
            scope.sets.update(
                target.id for target in child.targets if isinstance(target, ast.Name)
            )
        elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
            if _is_set_annotation(child.annotation) or (
                child.value is not None and _is_set(child.value, scopes)
            ):
                scope.sets.add(child.target.id)
    return scope


# -- the scan ----------------------------------------------------------------------------


class _Scanner(ast.NodeVisitor):
    """Walks a module with the scopes in force, collecting what the rules reject."""

    def __init__(self, module: ast.Module) -> None:
        self.findings: list[Finding] = []
        self._scopes: list[_Scope] = [_scope_of(module, [])]
        self._order_free: list[ast.expr] = []
        self.generic_visit(module)

    def visit(self, node: ast.AST) -> None:
        if isinstance(node, _SCOPES):
            self._scopes.append(_scope_of(node, self._scopes))
            self.generic_visit(node)
            self._scopes.pop()
            return
        if isinstance(node, ast.Import):
            for alias in node.names:
                self._module(node, alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module is not None:
                self._module(node, node.module)
        elif isinstance(node, ast.Call):
            self._call(node)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            self._iterates(node.iter, "a for loop")
        elif isinstance(node, (ast.ListComp, ast.DictComp, ast.GeneratorExp)):
            if not any(node is free for free in self._order_free):
                for generator in node.generators:
                    self._iterates(generator.iter, "a comprehension")
        elif isinstance(node, ast.Starred):
            self._iterates(node.value, "unpacking")
        elif isinstance(node, ast.FormattedValue):
            self._iterates(node.value, "an f-string field")
        self.generic_visit(node)

    def _report(self, node: ast.expr | ast.stmt, rule: str, message: str) -> None:
        self.findings.append(Finding(node.lineno, rule, message))

    def _module(self, node: ast.expr | ast.stmt, name: str) -> None:
        if name.split(".")[0] in PROHIBITED_MODULES:
            self._report(
                node, IMPORT, f"imports {name}, whose values differ between runs"
            )

    def _iterates(self, expression: ast.expr, how: str) -> None:
        if _is_set(expression, self._scopes):
            self._report(
                expression,
                SET_ITERATION,
                f"{how} iterates a set, whose order differs between processes",
            )

    def _call(self, node: ast.Call) -> None:
        function = node.func
        name = function.id if isinstance(function, ast.Name) else None
        if name in PROHIBITED_CALLS:
            self._report(
                node, CALL, f"calls {name}(), whose result differs between runs"
            )
        if name == "__import__" or _tail(function) == "import_module":
            argument = node.args[0] if node.args else None
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                self._module(node, argument.value)
        consumer = name if name in _ORDERED_CONSUMERS else None
        if isinstance(function, ast.Attribute) and function.attr in _ORDERED_METHODS:
            consumer = function.attr
        if consumer is not None:
            for argument in node.args:
                self._iterates(argument, f"{consumer}()")
        if name in _ORDER_FREE_CONSUMERS:
            self._order_free.extend(
                argument
                for argument in node.args
                if isinstance(argument, ast.GeneratorExp)
            )


def scan(source: str) -> list[Finding]:
    """Every prohibited construct in ``source``, in line order.

    :param source: a Python module's text.
    :return: what the rules reject and the module's allow comments do not
        cover, with a finding for each malformed or unused allow comment.
    :raises SyntaxError: if ``source`` does not parse.
    """
    found = _Scanner(ast.parse(source)).findings
    allowed, problems = _allowances(source)
    used: set[tuple[int, str]] = set()
    rejected: list[Finding] = []
    for finding in found:
        key = (finding.line, finding.rule)
        if key in allowed:
            used.add(key)
        else:
            rejected.append(finding)
    unused = [
        Finding(comment, ALLOW, f"allows {rule} on line {line}, where nothing needs it")
        for (line, rule), comment in allowed.items()
        if (line, rule) not in used
    ]
    return sorted(
        [*rejected, *problems, *unused],
        key=lambda finding: (finding.line, finding.rule, finding.message),
    )


def describe(path: Path, findings: Sequence[Finding]) -> str:
    """The findings of one module, a line each, for an assertion's message."""
    return "\n".join(
        f"{path.name}:{finding.line}: [{finding.rule}] {finding.message}"
        for finding in findings
    )


# -- the renderers -----------------------------------------------------------------------

SET_CONSTANTS: Final = (
    ("_escape.py", "_ROLE_SAFE"),
    ("_inplace.py", "_TEXT_BEARING"),
    ("_inplace.py", "_NO_ROLE"),
    ("_html.py", "_TEXT_BEARING"),
    ("_html.py", "_CHANGED"),
)
"""The module-level sets of the renderers: tested for membership, never iterated."""


def test_the_scan_reads_every_renderer_module() -> None:
    assert {path.name for path in MODULES} >= {
        "__init__.py",
        "_marks.py",
        "_escape.py",
        "_view.py",
        "_inplace.py",
        "_rich.py",
        "_html.py",
    }


@pytest.mark.parametrize("path", MODULES, ids=[path.name for path in MODULES])
def test_a_renderer_module_holds_no_prohibited_construct(path: Path) -> None:
    findings = scan(path.read_text(encoding="utf-8"))
    assert not findings, describe(path, findings)


def _annotated_as_sets(module: ast.Module) -> list[str]:
    """The module-level names whose annotation says set, read from the annotation alone."""
    return [
        statement.target.id
        for statement in module.body
        if isinstance(statement, ast.AnnAssign)
        and isinstance(statement.target, ast.Name)
        and re.search(r"\b(?:frozen)?set\[", ast.unparse(statement.annotation))
    ]


def test_the_set_constants_listed_here_are_all_the_renderers_define() -> None:
    found = [
        (path.name, name)
        for path in MODULES
        for name in _annotated_as_sets(ast.parse(path.read_text(encoding="utf-8")))
    ]
    assert sorted(found) == sorted(SET_CONSTANTS)


@pytest.mark.parametrize(("module", "constant"), SET_CONSTANTS)
def test_the_scan_would_find_a_loop_over_a_renderers_set_constant(
    module: str, constant: str
) -> None:
    """The constants pass because they are only tested for membership, not because the scan is blind to them."""
    source = (RENDERERS / module).read_text(encoding="utf-8")
    loop = f"{source}\n\nfor _member in {constant}:\n    pass\n"
    assert [finding.rule for finding in scan(loop)] == [SET_ITERATION]


# -- the scan, on modules written to be found --------------------------------------------

OFFENDING = """\
import time  # expect: import
import datetime as clock  # expect: import
from datetime import datetime  # expect: import
import random  # expect: import
from random import choice  # expect: import
import uuid  # expect: import
import secrets  # expect: import
import locale  # expect: import
from locale import format_string  # expect: import
import os.path
from . import time as local_time
from .random import choice as local_choice
from typing import Final

KINDS = frozenset({"insert", "delete"})
SEEN: Final[set[str]] = set()


def render(items, kinds: frozenset[str], flags: set[str] | None = None):
    token = id(items)  # expect: call
    digest = hash(items)  # expect: call
    module = __import__("time")  # expect: import
    for kind in {"insert", "delete"}:  # expect: set-iteration
        pass
    for kind in {item for item in items}:  # expect: set-iteration
        pass
    for kind in set(items):  # expect: set-iteration
        pass
    for kind in frozenset(items):  # expect: set-iteration
        pass
    for kind in KINDS:  # expect: set-iteration
        pass
    for kind in SEEN | KINDS:  # expect: set-iteration
        pass
    for kind in KINDS.union(items):  # expect: set-iteration
        pass
    for kind in kinds:  # expect: set-iteration
        pass
    for flag in flags:  # expect: set-iteration
        pass
    local = set(items)
    for kind in local:  # expect: set-iteration
        pass
    rest = local - KINDS
    for kind in rest:  # expect: set-iteration
        pass
    names = [name for name in KINDS]  # expect: set-iteration
    table = {name: 1 for name in KINDS}  # expect: set-iteration
    lazy = (name for name in KINDS)  # expect: set-iteration
    joined = ", ".join(KINDS)  # expect: set-iteration
    listed = list(KINDS)  # expect: set-iteration
    numbered = enumerate(KINDS)  # expect: set-iteration
    keyed = dict.fromkeys(KINDS)  # expect: set-iteration
    shown = str(KINDS)  # expect: set-iteration
    written = f"{KINDS}"  # expect: set-iteration
    spread = [*KINDS]  # expect: set-iteration
    return token, digest, module, names, table, lazy, joined, listed, numbered, keyed, shown, written, spread


async def render_later(items):
    async for kind in {1, 2}:  # expect: set-iteration
        pass


class Renderer:
    kinds = frozenset({"a"})
    for kind in kinds:  # expect: set-iteration
        pass

    def method(self):
        for kind in KINDS:  # expect: set-iteration
            pass
"""

ORDERED = """\
from typing import Final

KINDS: Final[frozenset[str]] = frozenset({"a", "b"})


def render(kind, items, kinds: frozenset[str]):
    if kind in KINDS:
        pass
    if kind not in {"a", "b"}:
        pass
    hits = [item for item in items if item in KINDS]
    ordered = sorted(KINDS)
    count = len(KINDS)
    more = KINDS | {"c"}
    same = {item for item in KINDS}
    texts = sorted(item.upper() for item in KINDS)
    present = any(item in kinds for item in KINDS)
    for item in sorted(kinds):
        pass
    for item in {"a": 1}:
        pass
    for item in (1, 2, 3):
        pass
    for item in [3, 2, 1]:
        pass
    for item in dict.fromkeys(items):
        pass
    for item in items:
        pass
    smallest = min(KINDS)
    return hits, ordered, count, more, same, texts, present, smallest


def shadowed(KINDS):
    for kind in KINDS:
        pass


class Holder:
    KINDS = ["a", "b"]

    def method(self):
        for kind in self.KINDS:
            pass
"""


def expected(source: str) -> list[tuple[int, str]]:
    """The ``(line, rule)`` pairs a module marks with ``# expect: RULE``."""
    marks = (
        (number, re.search(r"# expect: (?P<rule>[a-z-]+)\s*$", line))
        for number, line in enumerate(source.splitlines(), 1)
    )
    return [(number, match["rule"]) for number, match in marks if match]


def test_the_scan_finds_every_prohibited_construct_in_a_module_written_to_have_them() -> (
    None
):
    found = [(finding.line, finding.rule) for finding in scan(OFFENDING)]
    assert found == expected(OFFENDING)
    assert {rule for _, rule in found} == set(RULES)
    assert len(found) >= 30


def test_the_scan_passes_the_ways_of_using_a_set_that_leave_the_output_ordered() -> (
    None
):
    assert scan(ORDERED) == []


def test_a_finding_names_its_line_its_rule_and_the_reason() -> None:
    (finding,) = scan("KINDS = {1}\nfor kind in KINDS:\n    pass\n")
    assert (finding.line, finding.rule) == (2, SET_ITERATION)
    assert "for loop" in finding.message and "set" in finding.message


# -- allow comments ----------------------------------------------------------------------

ALLOWED = """\
import time  # determinism: allow import -- a stopwatch whose reading is never written out
# determinism: allow call -- a cache key, never an output
key = id(object())
KINDS = frozenset({1})
for kind in KINDS:  # determinism: allow set-iteration -- the body only counts
    total = 1
"""


def test_an_allow_comment_with_a_rule_and_a_reason_lets_that_construct_through() -> (
    None
):
    assert scan(ALLOWED) == []


@pytest.mark.parametrize(
    ("source", "expected_findings"),
    [
        pytest.param(
            "import time  # determinism: allow call -- not what is on this line\n",
            [(1, ALLOW), (1, IMPORT)],
            id="the-wrong-rule",
        ),
        pytest.param(
            "import time  # determinism: allow import\n",
            [(1, ALLOW), (1, IMPORT)],
            id="no-reason",
        ),
        pytest.param(
            "import time  # determinism: allow import --\n",
            [(1, ALLOW), (1, IMPORT)],
            id="an-empty-reason",
        ),
        pytest.param(
            "import time  # determinism: allow anything -- reasons\n",
            [(1, ALLOW), (1, IMPORT)],
            id="an-unknown-rule",
        ),
        pytest.param(
            "# determinism: allow import -- two lines up\n\nimport time\n",
            [(1, ALLOW), (3, IMPORT)],
            id="not-the-next-line",
        ),
        pytest.param(
            "value = 1  # determinism: allow import -- nothing here imports\n",
            [(1, ALLOW)],
            id="nothing-to-allow",
        ),
        pytest.param(
            "import time\n# determinism: allow import -- above it, not below\n",
            [(1, IMPORT), (2, ALLOW)],
            id="the-comment-below",
        ),
    ],
)
def test_an_allow_comment_that_is_wrong_is_a_finding_and_lets_nothing_through(
    source: str, expected_findings: list[tuple[int, str]]
) -> None:
    assert [(f.line, f.rule) for f in scan(source)] == expected_findings


def test_one_allow_comment_can_name_several_rules() -> None:
    source = (
        "import time\n"
        "# determinism: allow call,import -- both, deliberately\n"
        "import random; token = id(time)\n"
    )
    assert [(f.line, f.rule) for f in scan(source)] == [(1, IMPORT)]
