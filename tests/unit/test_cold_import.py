"""Every module of this distribution imports first, on an interpreter that holds none."""

from __future__ import annotations

import subprocess
import sys


def test_no_module_needs_another_one_imported_first() -> None:
    """A cycle inside the distribution shows up as the first import that fails."""
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import importlib
import pkgutil
import sys

import veupathdb_mcp

names = [
    info.name
    for info in pkgutil.walk_packages(veupathdb_mcp.__path__, prefix="veupathdb_mcp.")
    if not info.name.startswith("veupathdb_mcp.alembic")
    and not info.name.endswith("__main__")
]

broken = []
for name in ["veupathdb_mcp", *sorted(names)]:
    for loaded in [key for key in sys.modules if key.startswith("veupathdb_mcp")]:
        del sys.modules[loaded]
    try:
        importlib.import_module(name)
    except ImportError as error:
        broken.append(f"{name}: {error}")

print("\\n".join(broken))
""",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip() == ""
