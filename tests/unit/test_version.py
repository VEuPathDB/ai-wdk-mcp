"""The build backend and the runtime read one version literal."""

from __future__ import annotations

import tomllib
from importlib.metadata import version
from pathlib import Path

import veupathdb_mcp

PYPROJECT = Path(__file__).parent.parent.parent / "pyproject.toml"


def _project_table() -> dict[str, object]:
    return tomllib.loads(PYPROJECT.read_text())["project"]


def test_the_distribution_version_is_the_module_literal() -> None:
    assert version("veupathdb-mcp") == veupathdb_mcp.__version__


def test_pyproject_names_the_module_as_the_only_version_source() -> None:
    project = _project_table()
    hatch = tomllib.loads(PYPROJECT.read_text())["tool"]["hatch"]["version"]

    assert "version" not in project
    assert project["dynamic"] == ["version"]
    assert hatch["path"] == "src/veupathdb_mcp/__init__.py"
