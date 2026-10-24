"""The recordings this distribution ships for its own suite and for a host's suite."""

import atexit
from contextlib import ExitStack
from importlib.resources import as_file, files
from pathlib import Path

_RESOURCES = ExitStack()
atexit.register(_RESOURCES.close)


def package_file(name: str) -> Path:
    return _RESOURCES.enter_context(as_file(files("veupathdb_mcp.testing") / name))


FIXTURE_ROOT: Path = package_file("fixtures")
ORTHOMCL_COUNTS: Path = FIXTURE_ROOT / "orthomcl"
ORTHOMCL_GROUP_CLOUDS: Path = ORTHOMCL_COUNTS / "group_clouds"
