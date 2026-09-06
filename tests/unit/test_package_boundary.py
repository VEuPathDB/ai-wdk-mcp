"""The boundary is an installation fact; this suite is the belt.

The package declares no dependency on ``pathfinder``, ``assistant-core`` or an
agent framework, so those imports cannot resolve in this environment. The walk
below fails on the import statement instead, and names the module that added it.
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

import veupathdb_mcp

SERVER = veupathdb_mcp.__name__

FORBIDDEN_ROOTS = {
    "pathfinder",
    "assistant_core",
    "pydantic_ai",
    "langgraph",
    "fastapi",
}

ENTRYPOINT = f"{SERVER}.__main__"

# Alembic runs its migrations at import, so the chain is read, never imported.
MIGRATIONS = f"{SERVER}.alembic"

# The server owns its process, so one module configures its logging.
LOGGING_OWNER = f"{SERVER}.logging_setup"


def _server_modules() -> list[ModuleType]:
    return [
        veupathdb_mcp,
        *(
            importlib.import_module(info.name)
            for info in pkgutil.walk_packages(
                veupathdb_mcp.__path__,
                prefix=f"{SERVER}.",
            )
            if not info.name.startswith(f"{MIGRATIONS}.")
        ),
    ]


def _imported_names(module: ModuleType) -> set[str]:
    path = module.__file__
    assert path is not None
    names: set[str] = set()
    for node in ast.walk(ast.parse(Path(path).read_text())):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


def _distributions(names: set[str]) -> set[str]:
    roots = {name.split(".")[0] for name in names}
    return {root for root in roots if root not in sys.stdlib_module_names} - {SERVER}


@pytest.mark.parametrize("module", _server_modules(), ids=lambda m: m.__name__)
def test_no_module_reaches_a_host_or_an_agent(module: ModuleType) -> None:
    assert _distributions(_imported_names(module)) & FORBIDDEN_ROOTS == set()


def test_the_served_entrypoint_reaches_no_host() -> None:
    """A second deployment of the entrypoint carries no application with it."""
    by_name = {module.__name__: module for module in _server_modules()}
    seen = {ENTRYPOINT}
    pending = [ENTRYPOINT]
    reached: set[str] = set()
    while pending:
        module = by_name[pending.pop()]
        for name in _imported_names(module):
            reached.add(name.split(".")[0])
            if name in by_name and name not in seen:
                seen.add(name)
                pending.append(name)

    assert reached & FORBIDDEN_ROOTS == set()


def test_only_the_server_configures_logging() -> None:
    offenders = [
        module.__name__
        for module in _server_modules()
        if "structlog.configure" in Path(str(module.__file__)).read_text()
    ]

    assert offenders == [LOGGING_OWNER]


def test_the_migration_chain_declares_the_two_tables_it_owns() -> None:
    """The chain ships in the package, so an installed distribution can run it."""
    versions = Path(str(veupathdb_mcp.__file__)).parent / "alembic" / "versions"
    written = "\n".join(path.read_text() for path in versions.glob("*.py"))

    assert versions.is_dir()
    assert '"embedding_vectors"' in written
    assert '"embedding_index_entries"' in written
