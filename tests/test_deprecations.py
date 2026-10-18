"""The deprecation mechanism (R46; ADR-0036).

redlines 1.0 ships the means to deprecate something, and deprecates nothing at
runtime: two warning categories, the one function that raises them, a pytest
tripwire and a written schedule (``redlines/_deprecation.py`` has the schedule).
This module checks each part, and the promise.

- The categories exist, are defined in ``redlines._deprecation``, are exported from
  ``redlines``, and extend the standard categories they are named for. They do not
  extend one another, so a filter on one never catches the other.
- ``warn_deprecated`` emits exactly the category it is given, and must be given one,
  with the message ``"{old} is deprecated since redlines {since}; use {new}
  instead."``, attributed to the caller of the deprecated function.
- The tripwire in ``pyproject.toml`` is armed for both categories, and for nothing
  broader: ``error::DeprecationWarning`` would fail on click 8.5's own warning.
- Nothing in the package mentions ``warn_deprecated``, or names either category but
  to define and export them, which is the promise of 1.0; and the three names that
  1.1 will warn on say in their docstrings that they are superseded.

``tests/test_quick_path_is_silent.py`` holds the other half of the promise, for what a
0.6 user copies, runs or types. It counts a warning as redlines' own when its category
is defined in the package, wherever ``stacklevel`` makes it point, and a deprecation
warning points at the user's code, so that rule is the one that sees it. That module
tries the rule on stand-in classes; what is pinned here is the premise, that the real
categories are defined in the package.

When 1.1 puts the first warning on ``changes``, ``redlines`` and ``get_changes``, the
two tests that scan the package change with it, to assert that exactly those three
names call ``warn_deprecated`` and that they do it through a private ``_changes()``.
The rest of this module stays as it is.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import linecache
import re
import sys
import warnings
from collections.abc import Callable
from pathlib import Path

import pytest

import redlines
import redlines._deprecation as deprecation
from redlines import (
    Redlines,
    RedlinesDeprecationWarning,
    RedlinesPendingDeprecationWarning,
)
from redlines._deprecation import warn_deprecated

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = REPO_ROOT / "redlines"
THIS_FILE = Path(__file__).resolve()

Category = type[RedlinesPendingDeprecationWarning] | type[RedlinesDeprecationWarning]

BOTH_CATEGORIES = [
    pytest.param(RedlinesPendingDeprecationWarning, id="pending"),
    pytest.param(RedlinesDeprecationWarning, id="deprecation"),
]


# --- stand-ins for a deprecated name of redlines ---------------------------
#
# `warn_deprecated` attributes the warning to the caller of the function that
# called it, so a test needs a function in between: calling `warn_deprecated`
# straight from a test names whatever called the test.


def deprecated_function() -> None:
    warn_deprecated(
        "old_name", "new_name", since="1.1", category=RedlinesPendingDeprecationWarning
    )


def deprecated_function_in(category: Category) -> None:
    warn_deprecated("old_name", "new_name", since="1.1", category=category)


def deprecated_function_at(stacklevel: int) -> None:
    warn_deprecated(
        "old_name",
        "new_name",
        since="1.1",
        category=RedlinesPendingDeprecationWarning,
        stacklevel=stacklevel,
    )


def same_file(filename: str, expected: Path) -> bool:
    return Path(filename).resolve() == expected.resolve()


def source_line(warning: warnings.WarningMessage) -> str:
    """The line of source that a warning names."""
    return linecache.getline(warning.filename, warning.lineno).strip()


def lines_of(function: Callable[..., object]) -> range:
    """The lines of this file that a function's source covers."""
    source, first = inspect.getsourcelines(function)
    return range(first, first + len(source))


# --- the categories --------------------------------------------------------


@pytest.mark.parametrize(
    ("ours", "standard"),
    [
        pytest.param(
            RedlinesPendingDeprecationWarning, PendingDeprecationWarning, id="pending"
        ),
        pytest.param(RedlinesDeprecationWarning, DeprecationWarning, id="deprecation"),
    ],
)
def test_a_category_extends_the_standard_one_it_is_named_for(
    ours: Category, standard: type[Warning]
) -> None:
    assert ours.__bases__ == (standard,)


def test_the_categories_are_separate() -> None:
    assert not issubclass(RedlinesPendingDeprecationWarning, RedlinesDeprecationWarning)
    assert not issubclass(RedlinesDeprecationWarning, RedlinesPendingDeprecationWarning)
    # So a filter on one standard category catches only the phase it belongs to.
    assert not issubclass(RedlinesPendingDeprecationWarning, DeprecationWarning)
    assert not issubclass(RedlinesDeprecationWarning, PendingDeprecationWarning)


def test_both_categories_are_exported_from_redlines() -> None:
    assert (
        redlines.RedlinesPendingDeprecationWarning
        is deprecation.RedlinesPendingDeprecationWarning
    )
    assert redlines.RedlinesDeprecationWarning is deprecation.RedlinesDeprecationWarning


def test_warn_deprecated_is_not_part_of_the_public_surface() -> None:
    assert not hasattr(redlines, "warn_deprecated")


# --- warn_deprecated -------------------------------------------------------


def test_category_is_required_and_has_no_default() -> None:
    """A call that moves on to 1.2 must not be able to go on raising the pending
    category, which Python hides, by forgetting to change it."""
    category = inspect.signature(warn_deprecated).parameters["category"]
    assert category.kind is inspect.Parameter.KEYWORD_ONLY
    assert category.default is inspect.Parameter.empty

    with pytest.raises(TypeError, match="category"):
        warn_deprecated("old_name", "new_name", since="1.1")  # type: ignore[call-arg]


@pytest.mark.parametrize("category", BOTH_CATEGORIES)
def test_warn_deprecated_emits_exactly_the_category_it_is_given(
    category: Category,
) -> None:
    with pytest.warns(category) as record:
        deprecated_function_in(category)

    [warning] = record
    assert warning.category is category
    assert type(warning.message) is category


def test_the_message_names_old_new_and_since_on_one_line() -> None:
    with pytest.warns(RedlinesPendingDeprecationWarning) as record:
        warn_deprecated(
            "Redlines.changes",
            "redlines.compare(...).changes",
            since="1.1",
            category=RedlinesPendingDeprecationWarning,
        )

    message = str(record[0].message)
    assert message == (
        "Redlines.changes is deprecated since redlines 1.1; "
        "use redlines.compare(...).changes instead."
    )
    assert "\n" not in message
    # 1.0 promises no removal before 2.0, so a message does not name a date.
    assert "remov" not in message.lower()


def test_the_warning_is_attributed_to_the_caller_of_the_deprecated_function() -> None:
    with pytest.warns(RedlinesPendingDeprecationWarning) as record:
        deprecated_function()

    [warning] = record
    assert same_file(warning.filename, THIS_FILE)
    assert source_line(warning) == "deprecated_function()"


def test_stacklevel_is_passed_to_warnings_warn() -> None:
    with pytest.warns(RedlinesPendingDeprecationWarning) as record:
        deprecated_function_at(1)
    [here] = record
    assert same_file(here.filename, Path(deprecation.__file__))

    with pytest.warns(RedlinesPendingDeprecationWarning) as record:
        deprecated_function_at(2)
    [inside] = record
    assert same_file(inside.filename, THIS_FILE)
    assert inside.lineno in lines_of(deprecated_function_at)


# --- the tripwire ----------------------------------------------------------


def parse_filter(entry: str) -> tuple[str, str, str]:
    """The action, message and category of one ``filterwarnings`` entry, split the
    way pytest splits it (``action:message:category:module:lineno``)."""
    fields = [field.strip() for field in entry.split(":")]
    fields += [""] * (3 - len(fields))
    action, message, category = fields[:3]
    return action, message, category


def resolve_category(name: str) -> type[Warning]:
    if not name:
        return Warning
    module_name, _, attribute = name.rpartition(".")
    resolved = getattr(importlib.import_module(module_name or "builtins"), attribute)
    assert isinstance(resolved, type) and issubclass(resolved, Warning), name
    return resolved


def test_the_pytest_configuration_names_both_categories(
    pytestconfig: pytest.Config,
) -> None:
    configured = pytestconfig.getini("filterwarnings")

    assert "error::redlines.RedlinesPendingDeprecationWarning" in configured
    assert "error::redlines.RedlinesDeprecationWarning" in configured


def test_the_pytest_configuration_does_not_catch_other_deprecations(
    pytestconfig: pytest.Config,
) -> None:
    """Never ``error::DeprecationWarning``, nor anything wider that matches it
    (``error``, ``error::Warning``): click 8.5 warns about itself, and a dependency
    bump must not break the suite. An entry scoped by message is left alone."""
    for entry in pytestconfig.getini("filterwarnings"):
        action, message, category = parse_filter(entry)
        if not action or not "error".startswith(action) or message:
            continue
        caught = resolve_category(category)
        assert not issubclass(DeprecationWarning, caught), entry
        assert not issubclass(PendingDeprecationWarning, caught), entry


def test_a_plain_deprecation_is_not_an_error_under_the_configuration() -> None:
    # No simplefilter here: the filters pytest set up for this test are in force.
    with warnings.catch_warnings(record=True):
        warnings.warn("another library's deprecation", DeprecationWarning)
        warnings.warn("another library's pending one", PendingDeprecationWarning)


@pytest.mark.parametrize("category", BOTH_CATEGORIES)
def test_either_category_is_an_error_under_the_configuration(
    category: Category,
) -> None:
    """The tripwire: outside ``pytest.warns``, which would record the warning, the
    filters in ``pyproject.toml`` turn it into the exception that fails a test."""
    with pytest.raises(category, match="old_name is deprecated since redlines 1.1"):
        deprecated_function_in(category)


# --- the quick path --------------------------------------------------------
#
# `tests/test_quick_path_is_silent.py` counts a recorded warning as redlines' own when
# its category is defined in the package (its second rule), wherever `stacklevel`
# makes it point. A deprecation warning is raised with stacklevel=3, so it names the
# user's file and only that rule can catch it. That module tries the rule on
# stand-in classes, so what is pinned here is the premise, for the real ones.


@pytest.mark.parametrize("category", BOTH_CATEGORIES)
def test_a_category_is_defined_in_the_redlines_package(category: Category) -> None:
    assert category.__module__ == "redlines._deprecation"


# --- nothing warns in 1.0 --------------------------------------------------
#
# These tests are the "no runtime warning in 1.0" promise, kept in the source. They
# flip in 1.1, when the three names start to warn.


def mentions_of(source: str, names: frozenset[str]) -> list[int]:
    """The lines that use one of ``names``: as a name, as an attribute, as an imported
    name (under its own name or another), or as a string (``getattr(module, "Name")``).
    A search for calls would miss ``from ._deprecation import warn_deprecated as w``;
    this does not."""
    lines = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name) and node.id in names:
            lines.append(node.lineno)
        elif isinstance(node, ast.Attribute) and node.attr in names:
            lines.append(node.lineno)
        elif isinstance(node, ast.alias) and node.name.rpartition(".")[2] in names:
            lines.append(node.lineno)
        elif isinstance(node, ast.Constant) and node.value in names:
            lines.append(node.lineno)
    return sorted(lines)


def package_sources() -> dict[Path, str]:
    return {
        path: path.read_text(encoding="utf-8")
        for path in sorted(PACKAGE_DIR.rglob("*.py"))
    }


def test_the_scan_finds_what_it_looks_for() -> None:
    """A scan that never matches would let the two tests below pass for the wrong
    reason."""
    names = frozenset({"warn_deprecated"})
    assert mentions_of("warn_deprecated('a', 'b', since='1')", names) == [1]
    assert mentions_of("x.y.warn_deprecated('a', 'b', since='1')", names) == [1]
    assert mentions_of("import m\nm.warn_deprecated()", names) == [2]
    assert mentions_of("from m import warn_deprecated as w", names) == [1]
    assert mentions_of("from m import warn_deprecated", names) == [1]
    assert mentions_of("getattr(m, 'warn_deprecated')", names) == [1]
    assert mentions_of("def warn_deprecated(): ...", names) == []
    assert mentions_of("print(warn_deprecated_twice)", names) == []
    assert mentions_of("import redlines._deprecation as d", names) == []

    categories = frozenset({"Category"})
    assert mentions_of("raise Category", categories) == [1]
    assert mentions_of("from m import Category as C", categories) == [1]
    assert mentions_of("category = None", categories) == []

    sources = package_sources()
    assert PACKAGE_DIR / "_deprecation.py" in sources
    assert PACKAGE_DIR / "redlines.py" in sources


def test_nothing_in_the_package_uses_warn_deprecated() -> None:
    """1.0 has the mechanism and no runtime warning (ADR-0036): ``warn_deprecated``
    is defined in ``_deprecation.py`` and named nowhere else, so it is neither
    called nor imported under another name. 1.1 flips this: the three public names
    call it, through a private ``_changes()``."""
    uses = {
        path.relative_to(REPO_ROOT).as_posix(): lines
        for path, source in package_sources().items()
        if path != PACKAGE_DIR / "_deprecation.py"
        and (lines := mentions_of(source, frozenset({"warn_deprecated"})))
    }

    assert uses == {}


def test_only_the_definition_and_the_export_name_the_categories() -> None:
    """Nor does anything raise a category without ``warn_deprecated``, as in
    ``warnings.warn(message, RedlinesDeprecationWarning)``. Only the module that
    defines the categories and the package ``__init__`` that exports them may name
    them. 1.1 flips this together with the test above."""
    names = frozenset(
        {"RedlinesPendingDeprecationWarning", "RedlinesDeprecationWarning"}
    )
    allowed = {PACKAGE_DIR / "_deprecation.py", PACKAGE_DIR / "__init__.py"}
    mentions = {
        path.relative_to(REPO_ROOT).as_posix(): lines
        for path, source in package_sources().items()
        if path not in allowed and (lines := mentions_of(source, names))
    }

    assert mentions == {}


# --- the schedule in the docstrings ----------------------------------------

# The successor is spelled `Comparison.changes`, from `redlines.compare(...)`, and not
# `redlines.compare(...).changes`: pdoc reads a dot that follows a bracket as a relative
# reference to a sibling module, and `redlines.changes` is one, so it turns the second
# spelling into "redlines.compare(...)redlines.changes" with a link to that module.
SUPERSEDED = (
    "Superseded by `Comparison.changes`, from `redlines.compare(...)` "
    "(block-addressed, character offsets; not a drop-in replacement). "
    "Not deprecated in 1.0; not removed before 2.0."
)


@pytest.mark.skipif(sys.flags.optimize >= 2, reason="python -OO strips docstrings")
@pytest.mark.parametrize("name", ["changes", "redlines", "get_changes"])
def test_a_name_that_is_superseded_says_so_in_its_docstring(name: str) -> None:
    doc = inspect.getdoc(getattr(Redlines, name))

    assert doc is not None
    assert SUPERSEDED in " ".join(doc.split())
    # Plain text: pdoc renders the docstring, and does not know a Sphinx directive.
    assert ".. deprecated::" not in doc
    # And no `).changes`, which pdoc rewrites (see SUPERSEDED).
    assert ").changes" not in doc
    # Ahead of the reST fields: pdoc would read what follows ``:return:`` as part
    # of the return value's description.
    first_field = re.search(r"^:\w+", doc, re.MULTILINE)
    assert first_field is not None
    assert doc.index("Superseded by") < first_field.start()
