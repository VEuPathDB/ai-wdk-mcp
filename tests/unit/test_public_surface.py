"""Every surface is the checked-in one, and every name on it resolves."""

from __future__ import annotations

import ast
import importlib
import inspect
import json
from pathlib import Path
from types import ModuleType

import pytest

PACKAGES = (
    "veupathdb_mcp",
    "veupathdb_mcp.catalog",
    "veupathdb_mcp.controls",
    "veupathdb_mcp.embeddings",
    "veupathdb_mcp.gene_lookup",
    "veupathdb_mcp.research",
    "veupathdb_mcp.tools",
    "veupathdb_mcp.wdk",
    "veupathdb_mcp.wdk.enrichment",
)

# The root modules a host reads by name. They stay off the root surface: an
# eager re-export would pull alembic and the catalog into the research process.
MODULES = (
    "veupathdb_mcp.migrate",
    "veupathdb_mcp.server",
    "veupathdb_mcp.tool_meta",
    "veupathdb_mcp.tool_payloads",
)

SURFACES = PACKAGES + MODULES

PUBLISHED = Path(__file__).parent / "published_surface.json"


def _package(name: str) -> ModuleType:
    return importlib.import_module(name)


def _declared_names(source: Path) -> set[str]:
    """The names one module states itself, so an imported name does not count."""
    names: set[str] = set()
    for node in ast.parse(source.read_text()).body:
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                names.add(node.name)
            case ast.TypeAlias(name=ast.Name(id=alias)):
                names.add(alias)
            case ast.AnnAssign(target=ast.Name(id=target)):
                names.add(target)
            case ast.Assign(targets=targets):
                names.update(
                    target.id for target in targets if isinstance(target, ast.Name)
                )
            case _:
                pass
    return names


def _names_the_package_declares(name: str) -> set[str]:
    root = Path(str(_package(name).__file__)).parent
    return {
        declared
        for source in root.rglob("*.py")
        if source.name != "__init__.py"
        for declared in _declared_names(source)
    }


@pytest.mark.parametrize("name", PACKAGES)
def test_the_package_declares_a_surface(name: str) -> None:
    exported = _package(name).__all__

    assert len(exported) > 0
    assert sorted(set(exported)) == sorted(exported)


def test_every_surface_is_listed() -> None:
    published = json.loads(PUBLISHED.read_text())

    assert sorted(published) == sorted(SURFACES)


@pytest.mark.parametrize("name", SURFACES)
def test_the_surface_is_the_checked_in_one(name: str) -> None:
    """A name leaves a surface only by editing the list beside this test."""
    published = json.loads(PUBLISHED.read_text())

    assert sorted(_package(name).__all__) == published[name]


@pytest.mark.parametrize("name", SURFACES)
def test_every_exported_name_resolves(name: str) -> None:
    package = _package(name)
    bound = vars(package)
    missing = [entry for entry in package.__all__ if entry not in bound]

    assert missing == []


@pytest.mark.parametrize("name", SURFACES)
def test_no_exported_name_is_private(name: str) -> None:
    private = [entry for entry in _package(name).__all__ if entry.startswith("_")]

    assert private == []


@pytest.mark.parametrize("name", PACKAGES)
def test_every_exported_name_is_declared_in_this_package(name: str) -> None:
    """A surface republishes this package's own names, never another library's."""
    declared = _names_the_package_declares(name)
    outside = [entry for entry in _package(name).__all__ if entry not in declared]

    assert outside == []


@pytest.mark.parametrize("name", SURFACES)
def test_no_exported_name_is_a_submodule(name: str) -> None:
    """A consumer reads a name from a package, never a file path inside it."""
    package = _package(name)
    modules = [
        entry for entry in package.__all__ if inspect.ismodule(vars(package)[entry])
    ]

    assert modules == []
