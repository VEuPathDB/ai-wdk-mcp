from __future__ import annotations

import ast
import re
from pathlib import Path

import veupathdb_mcp.catalog
from veupathdb_mcp import tools

_CATALOG = Path(veupathdb_mcp.catalog.__file__).parent
_LOG_CALLS = frozenset({"debug", "info", "warning", "error", "exception", "critical"})


def _docstrings(tree: ast.Module) -> set[int]:
    owners = [tree] + [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    return {
        id(owner.body[0].value)
        for owner in owners
        if owner.body
        and isinstance(owner.body[0], ast.Expr)
        and isinstance(owner.body[0].value, ast.Constant)
    }


def _logged(tree: ast.Module) -> set[int]:
    return {
        id(inner)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _LOG_CALLS
        for argument in [*node.args, *(k.value for k in node.keywords)]
        for inner in ast.walk(argument)
    }


def _exported(tree: ast.Module) -> set[int]:
    return {
        id(inner)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets)
        for inner in ast.walk(node.value)
    }


def _literals(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text())
    skipped = _docstrings(tree) | _logged(tree) | _exported(tree)
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in skipped
    ]


def test_no_catalog_literal_names_a_served_tool() -> None:
    named = re.compile(
        rf"(?<![\w.\-/])(?:{'|'.join(map(re.escape, tools.__all__))})(?!\w)"
    )

    found = sorted(
        f"{path.relative_to(_CATALOG)}:{line}: {match.group(0)}"
        for path in _CATALOG.rglob("*.py")
        for line, text in _literals(path)
        for match in named.finditer(text)
    )

    assert found == []
