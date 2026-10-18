"""Import discipline for ``redlines/renderers/`` (ADR-0037, "Where the code lives").

From the markdown renderer on, ``redlines/comparison.py`` imports the renderer
functions at module top, so ``import redlines`` reaches every renderer --
including under Pyodide, where a dependency the browser cannot load breaks
the whole package. So:

- every import in a renderer module is the standard library, ``redlines``
  itself, or ``rich`` in ``_rich.py`` and nowhere else;
- a renderer module imports ``Comparison`` only under ``TYPE_CHECKING``, or
  the two modules would import each other;
- importing the package raises no warning, even with warnings as errors;
- nothing in the package is public yet: ``redlines`` gains no name.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

import redlines
import redlines.renderers

REPO_ROOT = Path(__file__).resolve().parent.parent
RENDERERS = REPO_ROOT / "redlines" / "renderers"
MODULES = sorted(RENDERERS.glob("*.py"))


def _is_type_checking(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _imports(module: ast.Module) -> list[tuple[ast.Import | ast.ImportFrom, bool]]:
    """Every import statement, and whether it sits under ``if TYPE_CHECKING:``."""
    found: list[tuple[ast.Import | ast.ImportFrom, bool]] = []

    def visit(node: ast.AST, guarded: bool) -> None:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            found.append((node, guarded))
            return
        if isinstance(node, ast.If) and _is_type_checking(node.test):
            for statement in node.body:
                visit(statement, True)
            for statement in node.orelse:
                visit(statement, guarded)
            return
        for child in ast.iter_child_nodes(node):
            visit(child, guarded)

    visit(module, False)
    return found


def test_the_renderer_package_has_the_modules_this_milestone_adds() -> None:
    assert {path.name for path in MODULES} >= {
        "__init__.py",
        "_marks.py",
        "_escape.py",
        "_view.py",
        "_inplace.py",
    }


@pytest.mark.parametrize("path", MODULES, ids=[path.name for path in MODULES])
def test_every_renderer_import_is_the_standard_library_or_redlines(path: Path) -> None:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node, _ in _imports(module):
        if isinstance(node, ast.ImportFrom) and node.level > 0:
            continue  # relative: inside redlines
        names = (
            [alias.name for alias in node.names]
            if isinstance(node, ast.Import)
            else [node.module or ""]
        )
        for name in names:
            top = name.split(".")[0]
            allowed = (
                top in sys.stdlib_module_names
                or top == "redlines"
                or (top == "rich" and path.name == "_rich.py")
            )
            assert allowed, f"{path.name} imports {name!r} (line {node.lineno})"


@pytest.mark.parametrize("path", MODULES, ids=[path.name for path in MODULES])
def test_a_renderer_imports_comparison_only_for_type_checking(path: Path) -> None:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node, guarded in _imports(module):
        if isinstance(node, ast.ImportFrom):
            target = node.module or ""
            names_comparison = (node.level > 0 and target == "comparison") or target == (
                "redlines.comparison"
            )
        else:
            names_comparison = any(alias.name == "redlines.comparison" for alias in node.names)
        if names_comparison:
            assert guarded, f"{path.name} imports the comparison module at run time"


def test_importing_the_renderers_raises_no_warning() -> None:
    subprocess.run(
        [
            sys.executable,
            "-W",
            "error",
            "-c",
            "import redlines, redlines.cli, redlines.renderers, redlines.renderers._marks, "
            "redlines.renderers._escape, redlines.renderers._view, redlines.renderers._inplace",
        ],
        check=True,
        cwd=REPO_ROOT,
    )


def test_nothing_in_the_renderers_is_public_yet() -> None:
    assert redlines.renderers.__all__ == ()
    for name in ("MarkSet", "LEGACY", "CRITIC", "BlockStatus", "ViewNode", "build_view", "render_inplace"):
        assert not hasattr(redlines, name), name
